from dataclasses import dataclass
from datetime import datetime, timezone
import json
from typing import Any
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from tenacity import Retrying, stop_after_attempt, wait_fixed

from app.db.models import (
    ATTACKTechnique,
    Campaign,
    CTIDocument,
    CorrelationRecord,
    DocumentEntityAssociation,
    DocumentTechniqueMapping,
    CampaignDocumentAssociation,
    GraphSyncState,
)
from app.graph.client import GraphUnavailableError, Neo4jClient
from app.graph.schema import entity_label, stable_id


@dataclass(frozen=True)
class GraphSyncResult:
    resource_id: UUID
    nodes_written: int
    relationships_written: int
    attempts: int


def _iso(value: datetime | None) -> str | None:
    return value.astimezone(timezone.utc).isoformat() if value else None


def _property(value: Any) -> Any:
    """Encode structured evidence as a Neo4j-compatible property value."""
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, sort_keys=True, default=str)
    return value


class GraphSynchronizer:
    def __init__(self, client: Neo4jClient, retries: int = 3) -> None:
        self.client = client
        self.retries = max(1, retries)

    async def sync_document(self, session: AsyncSession, document_id: UUID) -> GraphSyncResult:
        result = await session.execute(
            select(CTIDocument)
            .options(
                selectinload(CTIDocument.source),
                selectinload(CTIDocument.entity_associations).selectinload(
                    DocumentEntityAssociation.entity
                ),
                selectinload(CTIDocument.technique_mappings).selectinload(
                    DocumentTechniqueMapping.technique
                ),
                selectinload(CTIDocument.campaign_associations).selectinload(
                    CampaignDocumentAssociation.campaign
                ),
            )
            .where(CTIDocument.id == document_id)
        )
        document = result.scalar_one_or_none()
        if document is None:
            raise ValueError("Document not found")

        correlation_result = await session.execute(
            select(CorrelationRecord).where(
                or_(
                    CorrelationRecord.first_document_id == document_id,
                    CorrelationRecord.second_document_id == document_id,
                )
            )
        )
        correlations = list(correlation_result.scalars().all())
        state = await self._state(session, document_id)
        state.status = "running"
        state.attempt_count += 1
        state.last_error = None
        await session.flush()

        try:
            written = {"nodes": 0, "relationships": 0}
            for attempt in Retrying(
                stop=stop_after_attempt(self.retries),
                wait=wait_fixed(0.1),
                reraise=True,
            ):
                with attempt:
                    written = self._write_document(document, correlations)
        except Exception as exc:
            state.status = "failed"
            state.last_error = str(exc)
            await session.flush()
            raise GraphUnavailableError("Neo4j synchronization failed") from exc

        state.status = "synced"
        state.synced_at = datetime.now(timezone.utc)
        await session.flush()
        return GraphSyncResult(
            document_id,
            written["nodes"],
            written["relationships"],
            state.attempt_count,
        )

    async def _state(self, session: AsyncSession, document_id: UUID) -> GraphSyncState:
        result = await session.execute(
            select(GraphSyncState).where(
                GraphSyncState.resource_type == "document",
                GraphSyncState.resource_id == document_id,
            )
        )
        state = result.scalar_one_or_none()
        if state is None:
            state = GraphSyncState(
                resource_type="document",
                resource_id=document_id,
                status="pending",
                attempt_count=0,
            )
            session.add(state)
            await session.flush()
        return state

    def _write_document(
        self,
        document: CTIDocument,
        correlations: list[CorrelationRecord],
    ) -> dict[str, int]:
        report_id = stable_id("ThreatReport", document.id)
        source_id = stable_id("Source", document.source.id)
        self.client.run(
            "MERGE (report:ThreatReport {stable_id: $report_id}) "
            "SET report.name=$name, report.title=$title, report.source_url=$source_url, "
            "report.published_at=$published_at, report.collected_at=$collected_at, "
            "report.evidence=$evidence "
            "MERGE (source:Source {stable_id: $source_id}) "
            "SET source.name=$source_name, source.url=$source_url "
            "MERGE (report)-[relationship:REPORTED_BY]->(source) "
            "SET relationship.relationship_status='confirmed', "
            "relationship.relationship_origin='source_confirmed', "
            "relationship.observed_at=$collected_at",
            {
                "report_id": report_id,
                "name": document.normalized_title or document.title,
                "title": document.original_title or document.title,
                "source_url": document.original_url or document.source.base_url,
                "published_at": _iso(document.published_at),
                "collected_at": _iso(document.retrieved_at),
                "evidence": _property(document.provenance),
                "source_id": source_id,
                "source_name": document.source.name,
            },
        )
        nodes = 2
        relationships = 1
        for association in document.entity_associations:
            entity = association.entity
            label = entity_label(str(entity.entity_type))
            self.client.run(
                f"MERGE (entity:{label} {{stable_id: $entity_id}}) "
                "SET entity.name=$name, entity.entity_type=$entity_type, "
                "entity.normalized_value=$normalized_value "
                "WITH entity "
                "MATCH (report:ThreatReport {stable_id: $report_id}) "
                "MERGE (report)-[relationship:MENTIONS]->(entity) "
                "SET relationship.evidence=$evidence, relationship.confidence=$confidence, "
                "relationship.relationship_status='confirmed', "
                "relationship.relationship_origin='source_confirmed', "
                "relationship.observed_at=$observed_at",
                {
                    "entity_id": stable_id(label, entity.id),
                    "name": entity.canonical_name,
                    "entity_type": str(entity.entity_type),
                    "normalized_value": entity.normalized_value,
                    "report_id": report_id,
                    "evidence": association.evidence_text or association.mention_text,
                    "confidence": association.confidence,
                    "observed_at": _iso(association.extracted_at),
                },
            )
            nodes += 1
            relationships += 1
        for mapping in document.technique_mappings:
            technique = mapping.technique
            self.client.run(
                "MERGE (technique:ATTACKTechnique {stable_id: $technique_id}) "
                "SET technique.name=$name, technique.external_id=$external_id, "
                "technique.tactic=$tactic, technique.dataset_version=$dataset_version "
                "WITH technique "
                "MATCH (report:ThreatReport {stable_id: $report_id}) "
                "MERGE (report)-[relationship:USES_TECHNIQUE]->(technique) "
                "SET relationship.evidence=$evidence, relationship.confidence=$confidence, "
                "relationship.relationship_status=$status, "
                "relationship.relationship_origin=$origin",
                {
                    "technique_id": stable_id("ATTACKTechnique", technique.id),
                    "name": technique.name,
                    "external_id": technique.external_id,
                    "tactic": technique.tactic,
                    "dataset_version": technique.dataset_version,
                    "report_id": report_id,
                    "evidence": mapping.evidence,
                    "confidence": mapping.confidence,
                    "status": "confirmed" if mapping.mapping_status == "confirmed" else "inferred",
                    "origin": "source_confirmed" if mapping.mapping_status == "confirmed" else "system_inferred",
                },
            )
            nodes += 1
            relationships += 1
        for association in document.campaign_associations:
            campaign = association.campaign
            campaign_id = stable_id("Campaign", campaign.id)
            campaign_evidence = campaign.evidence or {}
            naming_evidence = campaign_evidence.get("naming", {})
            self.client.run(
                "MERGE (campaign:Campaign {stable_id: $campaign_id}) "
                "SET campaign.name=$name, campaign.status=$status, "
                "campaign.confidence=$confidence, campaign.description=$description, "
                "campaign.classification=$classification, "
                "campaign.naming_status=$naming_status, "
                "campaign.naming_metadata=$naming_metadata, "
                "campaign.evidence=$campaign_evidence "
                "WITH campaign "
                "MATCH (report:ThreatReport {stable_id: $report_id}) "
                "MERGE (report)-[relationship:PART_OF_CAMPAIGN]->(campaign) "
                "SET relationship.evidence=$evidence, relationship.confidence=$association_confidence, "
                "relationship.relationship_status=$status_value, "
                "relationship.relationship_origin=$origin",
                {
                    "campaign_id": campaign_id,
                    "name": campaign.name,
                    "status": str(campaign.status),
                    "confidence": campaign.confidence,
                    "description": campaign.description,
                    "classification": campaign_evidence.get("classification"),
                    "naming_status": naming_evidence.get("status"),
                    "naming_metadata": _property(naming_evidence),
                    "campaign_evidence": _property(campaign_evidence),
                    "report_id": report_id,
                    "evidence": _property(association.association_evidence),
                    "association_confidence": association.relevance_score,
                    "status_value": "confirmed" if association.association_type == "source_confirmed" else "inferred",
                    "origin": association.association_type,
                },
            )
            nodes += 1
            relationships += 1
        for correlation in correlations:
            first = stable_id("ThreatReport", correlation.first_document_id)
            second = stable_id("ThreatReport", correlation.second_document_id)
            self.client.run(
                "MATCH (first:ThreatReport {stable_id: $first}), "
                "(second:ThreatReport {stable_id: $second}) "
                "MERGE (first)-[relationship:RELATED_TO]->(second) "
                "SET relationship.probability=$probability, relationship.evidence=$evidence, "
                "relationship.relationship_status='inferred', relationship.relationship_origin='system_inferred'",
                {
                    "first": first,
                    "second": second,
                    "probability": correlation.correlation_probability,
                    "evidence": _property(correlation.evidence_and_explanation),
                },
            )
            relationships += 1
        return {"nodes": nodes, "relationships": relationships}
