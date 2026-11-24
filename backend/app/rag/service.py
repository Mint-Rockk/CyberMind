from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
import re
from typing import Any
from uuid import UUID

from qdrant_client.http.exceptions import ResponseHandlingException, UnexpectedResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.exc import SQLAlchemyError

from app.db.models import (
    ATTACKTechnique,
    Campaign,
    CampaignDocumentAssociation,
    CorrelationRecord,
    CTIDocument,
    DocumentEntityAssociation,
    DocumentTechniqueMapping,
    ExtractedEntity,
)
from app.graph.client import GraphUnavailableError
from app.graph.service import GraphQueryService
from app.vector_store.qdrant import SemanticRetrievalService

_TERM_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{1,}")


@dataclass(frozen=True)
class RetrievalFilters:
    campaign_id: UUID | None = None
    source_id: UUID | None = None
    published_after: datetime | None = None
    published_before: datetime | None = None
    document_type: str | None = None
    entity: str | None = None
    minimum_correlation_probability: float = 0.0


@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    evidence_type: str
    score: float
    document_id: UUID | None
    document_title: str | None
    source_url: str | None
    chunk_id: str | None
    relevant_text: str
    publication_timestamp: datetime | None
    source_reliability: float | None
    provenance: dict[str, Any]


@dataclass
class RetrievalResponse:
    query: str
    evidence: list[EvidenceItem]
    source_references: list[dict[str, Any]]
    context: str
    sufficient_evidence: bool
    warnings: list[str] = field(default_factory=list)


class HybridRetrievalService:
    """Combines Qdrant, PostgreSQL, and predefined Neo4j reads without generating claims."""

    def __init__(
        self,
        semantic: SemanticRetrievalService,
        graph: GraphQueryService | None = None,
    ) -> None:
        self.semantic = semantic
        self.graph = graph

    async def retrieve(
        self,
        session: AsyncSession,
        query: str,
        *,
        filters: RetrievalFilters | None = None,
        limit: int = 10,
    ) -> RetrievalResponse:
        if not query.strip():
            raise ValueError("Retrieval query cannot be empty")
        filters = filters or RetrievalFilters()
        limit = max(1, min(limit, 100))
        items: list[EvidenceItem] = []
        warnings: list[str] = []

        try:
            semantic_results = self.semantic.search(
                query,
                source_id=filters.source_id,
                published_after=filters.published_after,
                published_before=filters.published_before,
                document_type=filters.document_type,
                entity=filters.entity,
                limit=limit,
            )
            for result in semantic_results:
                metadata = result.metadata
                items.append(
                    EvidenceItem(
                        evidence_id=f"semantic:{result.chunk_id}",
                        evidence_type="semantic_chunk",
                        score=_bounded(result.score),
                        document_id=result.document_id,
                        document_title=_optional_str(metadata.get("title")),
                        source_url=_optional_str(metadata.get("source_url")),
                        chunk_id=result.chunk_id,
                        relevant_text=result.text,
                        publication_timestamp=_parse_datetime(metadata.get("published_at")),
                        source_reliability=_optional_float(metadata.get("source_reliability")),
                        provenance={
                            "retriever": "qdrant",
                            "collection": self.semantic.index.collection_name,
                            "embedding_model": metadata.get("embedding_model"),
                        },
                    )
                )
        except (ResponseHandlingException, UnexpectedResponse) as exc:
            warnings.append(f"semantic_retrieval_unavailable:{type(exc).__name__}")

        try:
            items.extend(await self._structured_retrieval(session, query, filters, limit))
        except SQLAlchemyError:
            warnings.append("structured_retrieval_unavailable")

        if self.graph is not None:
            try:
                items.extend(self._graph_retrieval(query, limit))
            except GraphUnavailableError:
                warnings.append("graph_retrieval_unavailable")

        ranked = _deduplicate_and_rank(items, limit)
        if not ranked:
            warnings.append("insufficient_evidence")
        references = [_reference(item) for item in ranked]
        context = "\n\n".join(
            f"[{item.evidence_id}] {item.document_title or item.evidence_type}: "
            f"{item.relevant_text}"
            for item in ranked
        )
        return RetrievalResponse(
            query=query,
            evidence=ranked,
            source_references=references,
            context=context,
            sufficient_evidence=bool(ranked),
            warnings=sorted(set(warnings)),
        )

    async def _structured_retrieval(
        self,
        session: AsyncSession,
        query: str,
        filters: RetrievalFilters,
        limit: int,
    ) -> list[EvidenceItem]:
        terms = _terms(query)
        if not terms and not filters.campaign_id:
            return []
        matches = [
            or_(
                CTIDocument.title.ilike(f"%{term}%"),
                CTIDocument.normalized_title.ilike(f"%{term}%"),
                CTIDocument.normalized_text.ilike(f"%{term}%"),
            )
            for term in terms
        ]
        document_query = (
            select(CTIDocument)
            .options(selectinload(CTIDocument.source))
            .where(or_(*matches) if matches else True)
            .order_by(CTIDocument.priority_score.desc().nullslast())
            .limit(limit)
        )
        if filters.source_id:
            document_query = document_query.where(CTIDocument.source_id == filters.source_id)
        if filters.document_type:
            document_query = document_query.where(CTIDocument.document_type == filters.document_type)
        if filters.published_after:
            document_query = document_query.where(CTIDocument.published_at >= filters.published_after)
        if filters.published_before:
            document_query = document_query.where(CTIDocument.published_at <= filters.published_before)
        documents = list((await session.execute(document_query)).scalars().all())
        items = [_document_evidence(document, query) for document in documents]
        document_ids = {document.id for document in documents}

        entity_query = (
            select(ExtractedEntity)
            .join(DocumentEntityAssociation)
            .join(CTIDocument)
            .options(
                selectinload(ExtractedEntity.document_associations)
                .selectinload(DocumentEntityAssociation.document)
                .selectinload(CTIDocument.source)
            )
            .where(
                or_(
                    ExtractedEntity.canonical_name.ilike(f"%{query}%"),
                    ExtractedEntity.normalized_value.ilike(f"%{query}%"),
                )
            )
            .limit(limit)
        )
        if filters.entity:
            entity_query = entity_query.where(
                ExtractedEntity.normalized_value == filters.entity
            )
        entities = list((await session.execute(entity_query)).scalars().unique().all())
        for entity in entities:
            for association in entity.document_associations:
                document = association.document
                if filters.source_id and document.source_id != filters.source_id:
                    continue
                if filters.document_type and document.document_type != filters.document_type:
                    continue
                document_ids.add(document.id)
                items.append(
                    EvidenceItem(
                        evidence_id=f"entity:{association.id}",
                        evidence_type="extracted_entity",
                        score=_bounded(association.confidence or entity.confidence or 0.6),
                        document_id=document.id,
                        document_title=document.title,
                        source_url=document.original_url or document.source.base_url,
                        chunk_id=None,
                        relevant_text=association.evidence_text or association.mention_text or entity.canonical_name,
                        publication_timestamp=document.published_at,
                        source_reliability=document.source.reliability_score,
                        provenance={
                            "retriever": "postgresql",
                            "entity_id": str(entity.id),
                            "entity_type": str(entity.entity_type),
                            "extraction_method": association.extraction_method,
                        },
                    )
                )

        attack_query = (
            select(ATTACKTechnique)
            .options(
                selectinload(ATTACKTechnique.document_mappings)
                .selectinload(DocumentTechniqueMapping.document)
                .selectinload(CTIDocument.source)
            )
            .where(
                or_(
                    ATTACKTechnique.external_id.ilike(f"%{query}%"),
                    ATTACKTechnique.name.ilike(f"%{query}%"),
                    ATTACKTechnique.description.ilike(f"%{query}%"),
                )
            )
            .limit(limit)
        )
        techniques = list((await session.execute(attack_query)).scalars().unique().all())
        for technique in techniques:
            if not technique.document_mappings:
                items.append(
                    EvidenceItem(
                        evidence_id=f"attack:{technique.id}",
                        evidence_type="attack_technique",
                        score=0.7,
                        document_id=None,
                        document_title=technique.name,
                        source_url=_attack_reference_url(technique.external_references),
                        chunk_id=None,
                        relevant_text=technique.description or technique.name,
                        publication_timestamp=None,
                        source_reliability=None,
                        provenance={
                            "retriever": "postgresql",
                            "attack_external_id": technique.external_id,
                            "dataset_version": technique.dataset_version,
                        },
                    )
                )
            for mapping in technique.document_mappings:
                document = mapping.document
                items.append(
                    EvidenceItem(
                        evidence_id=f"attack-mapping:{mapping.id}",
                        evidence_type="attack_technique_mapping",
                        score=_bounded(mapping.confidence or 0.6),
                        document_id=document.id,
                        document_title=document.title,
                        source_url=document.original_url or document.source.base_url,
                        chunk_id=None,
                        relevant_text=mapping.evidence or technique.name,
                        publication_timestamp=document.published_at,
                        source_reliability=document.source.reliability_score,
                        provenance={
                            "retriever": "postgresql",
                            "attack_external_id": technique.external_id,
                            "mapping_status": mapping.mapping_status,
                            "mapping_method": mapping.mapping_method,
                            "dataset_version": mapping.dataset_version or technique.dataset_version,
                        },
                    )
                )

        correlation_query = (
            select(CorrelationRecord)
            .options(
                selectinload(CorrelationRecord.first_document).selectinload(CTIDocument.source),
                selectinload(CorrelationRecord.second_document).selectinload(CTIDocument.source),
            )
            .where(
                CorrelationRecord.correlation_probability
                >= filters.minimum_correlation_probability
            )
            .order_by(CorrelationRecord.correlation_probability.desc())
            .limit(limit)
        )
        correlations = list((await session.execute(correlation_query)).scalars().all())
        for correlation in correlations:
            if document_ids and not (
                correlation.first_document_id in document_ids
                or correlation.second_document_id in document_ids
            ):
                continue
            document = correlation.first_document
            items.append(
                EvidenceItem(
                    evidence_id=f"correlation:{correlation.id}",
                    evidence_type="stored_correlation",
                    score=_bounded(correlation.correlation_probability),
                    document_id=document.id,
                    document_title=document.title,
                    source_url=document.original_url or document.source.base_url,
                    chunk_id=None,
                    relevant_text=(
                        f"Stored relationship between {correlation.first_document_id} and "
                        f"{correlation.second_document_id}: "
                        f"{correlation.evidence_and_explanation.get('explanation', 'correlation evidence')}"
                    ),
                    publication_timestamp=document.published_at,
                    source_reliability=document.source.reliability_score,
                    provenance={
                        "retriever": "postgresql",
                        "correlation_id": str(correlation.id),
                        "second_document_id": str(correlation.second_document_id),
                        "probability": correlation.correlation_probability,
                        "predictor_type": correlation.predictor_type,
                        "predictor_version": correlation.predictor_version,
                        "feature_schema_version": correlation.feature_schema_version,
                    },
                )
            )

        campaign_query = (
            select(Campaign)
            .options(
                selectinload(Campaign.document_associations)
                .selectinload(CampaignDocumentAssociation.document)
                .selectinload(CTIDocument.source)
            )
            .where(
                Campaign.id == filters.campaign_id
                if filters.campaign_id
                else or_(
                    Campaign.name.ilike(f"%{query}%"),
                    Campaign.description.ilike(f"%{query}%"),
                )
            )
            .limit(limit)
        )
        campaigns = list((await session.execute(campaign_query)).scalars().unique().all())
        for campaign in campaigns:
            for association in campaign.document_associations[:limit]:
                document = association.document
                items.append(
                    EvidenceItem(
                        evidence_id=f"campaign:{campaign.id}:{document.id}",
                        evidence_type="campaign_association",
                        score=_bounded(association.relevance_score or campaign.confidence or 0.5),
                        document_id=document.id,
                        document_title=document.title,
                        source_url=document.original_url or document.source.base_url,
                        chunk_id=None,
                        relevant_text=association.association_reason or campaign.description or campaign.name,
                        publication_timestamp=document.published_at,
                        source_reliability=document.source.reliability_score,
                        provenance={
                            "retriever": "postgresql",
                            "campaign_id": str(campaign.id),
                            "campaign_status": str(campaign.status),
                            "association_type": association.association_type,
                            "association_evidence": association.association_evidence,
                        },
                    )
                )
        return items

    def _graph_retrieval(self, query: str, limit: int) -> list[EvidenceItem]:
        assert self.graph is not None
        rows = self.graph.search(query, limit=limit)
        items: list[EvidenceItem] = []
        for index, row in enumerate(rows):
            node = _graph_value(row, "node")
            neighbor = _graph_value(row, "neighbor")
            relationship = _graph_value(row, "relationship")
            stable_node_id = _graph_property(node, "stable_id")
            document_id = _document_id_from_stable_id(stable_node_id)
            node_name = _graph_property(node, "name") or stable_node_id or "graph node"
            neighbor_name = _graph_property(neighbor, "name") or _graph_property(neighbor, "stable_id")
            relation_type = _graph_property(relationship, "relationship_type") or "related"
            items.append(
                EvidenceItem(
                    evidence_id=f"graph:{stable_node_id or index}",
                    evidence_type="graph_relationship",
                    score=0.55,
                    document_id=document_id,
                    document_title=str(node_name),
                    source_url=_graph_property(node, "source_url"),
                    chunk_id=None,
                    relevant_text=f"{node_name} {relation_type} {neighbor_name}",
                    publication_timestamp=_parse_datetime(_graph_property(node, "published_at")),
                    source_reliability=_optional_float(_graph_property(node, "source_reliability")),
                    provenance={
                        "retriever": "neo4j",
                        "stable_node_id": stable_node_id,
                        "relationship": relation_type,
                        "neighbor_stable_id": _graph_property(neighbor, "stable_id"),
                    },
                )
            )
        return items


def _document_evidence(document: CTIDocument, query: str) -> EvidenceItem:
    text = document.normalized_text or document.normalized_content
    score = 0.45 + min(0.35, sum(term in text.casefold() for term in _terms(query)) * 0.08)
    return EvidenceItem(
        evidence_id=f"document:{document.id}",
        evidence_type="structured_document",
        score=_bounded(score),
        document_id=document.id,
        document_title=document.title,
        source_url=document.original_url or document.source.base_url,
        chunk_id=None,
        relevant_text=text[:2000],
        publication_timestamp=document.published_at,
        source_reliability=document.source.reliability_score,
        provenance={"retriever": "postgresql", "source_id": str(document.source_id)},
    )


def _deduplicate_and_rank(items: list[EvidenceItem], limit: int) -> list[EvidenceItem]:
    strongest: dict[tuple[str, str], EvidenceItem] = {}
    for item in items:
        key = (
            str(item.document_id) if item.document_id else item.evidence_type,
            " ".join(item.relevant_text.casefold().split()),
        )
        if key not in strongest or item.score > strongest[key].score:
            strongest[key] = item
    return sorted(
        strongest.values(),
        key=lambda item: (-item.score, item.evidence_id),
    )[:limit]


def _reference(item: EvidenceItem) -> dict[str, Any]:
    return {
        "evidence_id": item.evidence_id,
        "document_id": str(item.document_id) if item.document_id else None,
        "document_title": item.document_title,
        "source_url": item.source_url,
        "chunk_id": item.chunk_id,
        "publication_timestamp": item.publication_timestamp.isoformat()
        if item.publication_timestamp
        else None,
        "source_reliability": item.source_reliability,
        "provenance": item.provenance,
    }


def _terms(query: str) -> list[str]:
    return list(dict.fromkeys(match.group(0).casefold() for match in _TERM_PATTERN.finditer(query)))


def _bounded(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None else None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _document_id_from_stable_id(value: Any) -> UUID | None:
    if not isinstance(value, str) or not value.startswith("ThreatReport:"):
        return None


def _attack_reference_url(references: list[dict[str, Any]]) -> str | None:
    for reference in references:
        url = reference.get("url")
        if url:
            return str(url)
    return None
    try:
        return UUID(value.split(":", 1)[1])
    except ValueError:
        return None


def _graph_value(row: Mapping[str, Any], key: str) -> Any:
    return row.get(key)


def _graph_property(value: Any, key: str) -> str | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        result = value.get(key)
    else:
        try:
            result = value.get(key)
        except AttributeError:
            result = None
    return str(result) if result is not None else None
