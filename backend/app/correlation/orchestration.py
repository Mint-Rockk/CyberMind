from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.correlation.candidates import CandidateDocument, generate_candidate_pairs
from app.correlation.behavioural import extract_behaviour_evidence
from app.correlation.service import calculate_features
from app.db.models import (
    CampaignDocumentAssociation,
    CorrelationJob,
    CorrelationJobStatus,
    CorrelationRecord,
    CTIDocument,
    CTISource,
    DocumentEntityAssociation,
    DocumentTechniqueMapping,
)
from app.graph.service import GraphQueryService
from app.ml.correlation.base import CorrelationPredictor
from app.ml.correlation.feature_schema import FEATURE_NAMES
from app.ml.correlation.predictor_factory import create_predictor
from app.vector_store.qdrant import SemanticRetrievalService


def _document_query():
    return (
        select(CTIDocument)
        .options(
            selectinload(CTIDocument.entity_associations).selectinload(
                DocumentEntityAssociation.entity
            ),
            selectinload(CTIDocument.technique_mappings).selectinload(
                DocumentTechniqueMapping.technique
            ),
            selectinload(CTIDocument.source),
        )
        .order_by(CTIDocument.created_at)
    )


def _candidate_document(document: CTIDocument) -> CandidateDocument:
    return CandidateDocument(
        document_id=document.id,
        published_at=document.published_at or document.retrieved_at,
        entities=frozenset(
            association.entity.normalized_value
            for association in document.entity_associations
            if association.entity is not None
            and str(association.entity.entity_type) != "campaign"
        ),
        attack_techniques=frozenset(
            mapping.technique.external_id
            for mapping in document.technique_mappings
            if mapping.technique is not None
        ),
    )


def _feature_document(
    document: CTIDocument,
    *,
    embedding: tuple[float, ...] | None = None,
    graph_relationships: tuple[tuple[str, str, str], ...] = (),
    graph_lookup_available: bool | None = None,
) -> dict[str, Any]:
    behaviours = extract_behaviour_evidence(
        document.normalized_text or document.normalized_content
    )
    return {
        "published_at": document.published_at or document.retrieved_at,
        "entities": [
            association.entity.normalized_value
            for association in document.entity_associations
            if association.entity is not None
            and str(association.entity.entity_type) != "campaign"
        ],
        "attack_techniques": [
            mapping.technique.external_id
            for mapping in document.technique_mappings
            if mapping.technique is not None
        ],
        "behaviours": [item.value for item in behaviours],
        "embedding": embedding,
        "knowledge_graph_relationships": graph_relationships,
        **(
            {"metadata": {"knowledge_graph_available": graph_lookup_available}}
            if graph_lookup_available is not None
            else {}
        ),
    }


def _model_report(document: CTIDocument) -> dict[str, Any]:
    entity_rows = [
        {
            "type": association.entity.entity_type,
            "normalized_name": association.entity.normalized_value,
        }
        for association in document.entity_associations
        if association.entity is not None
        and str(association.entity.entity_type) != "campaign"
    ]
    provenance_vendor = document.provenance.get("source_vendor") if document.provenance else None
    source_vendor = provenance_vendor or (
        document.source.name if document.source is not None else ""
    )
    return {
        "report_id": str(document.id),
        "normalized_text": document.normalized_text or document.normalized_content or "",
        "title": document.title,
        "source_vendor": str(source_vendor).casefold(),
        "source_url": document.original_url,
        "published_at": (
            document.published_at.isoformat() if document.published_at is not None else None
        ),
        "entities": entity_rows,
    }


def _label(probability: float, threshold: float) -> str:
    return "related" if probability >= threshold else "not_related"


async def _load_documents(
    session: AsyncSession,
    campaign_id: UUID | None,
    candidate_source_ids: set[UUID] | None,
) -> list[CTIDocument]:
    query = _document_query()
    if candidate_source_ids is not None:
        if not candidate_source_ids:
            return []
        query = query.where(CTIDocument.source_id.in_(candidate_source_ids))
    if campaign_id:
        query = query.join(
            CampaignDocumentAssociation,
            CampaignDocumentAssociation.document_id == CTIDocument.id,
        ).where(CampaignDocumentAssociation.campaign_id == campaign_id)
    result = await session.execute(query)
    return list(result.scalars().unique().all())


async def run_correlation_job(
    session: AsyncSession,
    job: CorrelationJob,
    *,
    predictor: CorrelationPredictor | None = None,
    semantic_neighbors: dict[UUID, set[UUID]] | None = None,
    graph_neighbors: dict[UUID, set[UUID]] | None = None,
    semantic_retrieval: SemanticRetrievalService | None = None,
    graph_client: Any | None = None,
    target_document_ids: set[UUID] | None = None,
    candidate_source_ids: set[UUID] | None = None,
) -> CorrelationJob:
    job.status = CorrelationJobStatus.RUNNING
    job.started_at = datetime.now(timezone.utc)
    await session.flush()
    try:
        predictor = predictor or create_predictor()
        if candidate_source_ids is None:
            demo_sources = (
                await session.scalars(
                    select(CTISource).where(
                        CTISource.configuration["local_demo_feed"].as_boolean().is_(True)
                    )
                )
            ).all()
            if demo_sources:
                candidate_source_ids = {s.id for s in demo_sources}
        documents = await _load_documents(
            session,
            job.campaign_id,
            candidate_source_ids,
        )
        if semantic_neighbors is None and semantic_retrieval is not None:
            semantic_neighbors = semantic_retrieval.neighbor_index(
                (
                    document.id,
                    document.normalized_text or document.normalized_content,
                )
                for document in documents
            )
        candidates = generate_candidate_pairs(
            [_candidate_document(document) for document in documents],
            semantic_neighbors=semantic_neighbors,
            graph_neighbors=graph_neighbors,
            target_document_ids=target_document_ids,
        )
        if job.document_id and target_document_ids is None:
            candidates = [
                candidate
                for candidate in candidates
                if job.document_id in {
                    candidate.first_document_id,
                    candidate.second_document_id,
                }
            ]
        job.pairs_considered = len(candidates)
        document_by_id = {document.id: document for document in documents}
        candidate_ids = {
            document_id
            for candidate in candidates
            for document_id in (candidate.first_document_id, candidate.second_document_id)
        }
        embeddings: dict[UUID, tuple[float, ...]] = {}
        graph_relationships: dict[UUID, tuple[tuple[str, str, str], ...]] = {}
        if candidate_ids and target_document_ids is not None:
            from app.vector_store.factory import get_semantic_index

            candidate_documents = [
                document_by_id[document_id]
                for document_id in sorted(candidate_ids, key=str)
                if document_id in document_by_id
            ]
            encoded = get_semantic_index().embedder.encode([
                item.normalized_text or item.normalized_content
                for item in candidate_documents
            ])
            embeddings = {
                item.id: tuple(vector)
                for item, vector in zip(candidate_documents, encoded, strict=True)
            }
            if graph_client is not None:
                graph_service = GraphQueryService(graph_client)
                graph_relationships = {
                    item.id: graph_service.relationship_triples(item.id)
                    for item in candidate_documents
                }
        metadata = predictor.get_model_metadata()
        job.predictor_type = str(metadata["model_type"])
        job.predictor_version = str(metadata["model_version"])
        feature_docs = {
            doc.id: _feature_document(
                doc,
                embedding=embeddings.get(doc.id),
                graph_relationships=graph_relationships.get(doc.id, ()),
                graph_lookup_available=graph_client is not None and target_document_ids is not None,
            )
            for doc in documents
        }
        model_reports = {
            doc.id: _model_report(doc)
            for doc in documents
        }
        existing_records = (
            await session.scalars(
                select(CorrelationRecord).where(
                    CorrelationRecord.predictor_version == metadata["model_version"]
                )
            )
        ).all()
        existing_map = {
            (r.first_document_id, r.second_document_id): r for r in existing_records
        }
        pair_data = []
        for candidate in candidates:
            first = document_by_id[candidate.first_document_id]
            second = document_by_id[candidate.second_document_id]
            vector = calculate_features(
                feature_docs[first.id],
                feature_docs[second.id],
            )
            pair_data.append((vector, model_reports[first.id], model_reports[second.id]))

        predictions = predictor.predict_pairs(pair_data)

        created = 0
        for candidate, (vector, _, _), (probability, model_evidence) in zip(
            candidates, pair_data, predictions, strict=True
        ):
            first = document_by_id[candidate.first_document_id]
            second = document_by_id[candidate.second_document_id]
            evidence = {
                "candidate_reasons": sorted(candidate.reasons),
                "features": vector.evidence,
                "model_evidence": model_evidence,
                "missing_features": [
                    name for name in FEATURE_NAMES if not vector.evidence[name]["available"]
                ],
                "explanation": (
                    "Probability produced by the configured "
                    f"{metadata.get('model_type', metadata.get('model_name', 'configured'))} "
                    "predictor from the canonical features and report evidence."
                ),
                "predictor_metadata": metadata,
                "correlation_job_id": str(job.id),
            }
            pair_key = (candidate.first_document_id, candidate.second_document_id)
            record = existing_map.get(pair_key)
            if record is None:
                record = CorrelationRecord(
                    first_document_id=candidate.first_document_id,
                    second_document_id=candidate.second_document_id,
                    predictor_version=metadata["model_version"],
                )
                session.add(record)
                existing_map[pair_key] = record
            values = dict(zip(FEATURE_NAMES, vector.values, strict=True))
            for feature_name, value in values.items():
                setattr(record, feature_name, value)
            record.correlation_probability = probability
            record.prediction_threshold = job.threshold
            record.predicted_relationship_label = _label(probability, job.threshold)
            record.predictor_type = metadata["model_type"]
            record.feature_schema_version = vector.schema_version
            record.evidence_and_explanation = evidence
            created += 1
        job.correlations_created = created
        job.status = CorrelationJobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
    except Exception as exc:
        job.status = CorrelationJobStatus.FAILED
        job.error_message = str(exc)
        job.completed_at = datetime.now(timezone.utc)
        raise
    await session.flush()
    return job
