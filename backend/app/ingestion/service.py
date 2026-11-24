import asyncio
import hashlib
import logging
import os
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.base import ConnectorConfig, ConnectorError
from app.collectors.registry import build_connector
from app.db.models import (
    CTIDocument,
    CTISource,
    DocumentStatus,
    IngestionJob,
    IngestionJobStatus,
    RawSourceRecord,
    SourceType,
)
from app.normalization.service import (
    find_duplicate,
    normalize_record,
    serialize_raw_content,
)
from app.extraction.service import persist_document_entities
from app.classification.service import apply_classification, classify_document, prioritize_document
from app.core.config import get_settings
from app.graph.client import Neo4jClient
from app.graph.sync import GraphSynchronizer
from app.demo.pipeline import process_demo_document

logger = logging.getLogger(__name__)


def _source_type_value(source_type: SourceType | str) -> str:
    return source_type.value if hasattr(source_type, "value") else str(source_type)


def build_connector_config(source: CTISource) -> ConnectorConfig:
    config = source.configuration or {}
    source_type_val = _source_type_value(source.source_type)
    api_key = None
    if source_type_val == "nvd":
        api_key = os.getenv("NVD_API_KEY")
    return ConnectorConfig(
        source_type=SourceType(source_type_val),
        endpoint_url=source.base_url,
        timeout_seconds=config.get("timeout_seconds", 30),
        max_retries=config.get("max_retries", 3),
        rate_limit_delay_seconds=config.get("rate_limit_delay_seconds", 0),
        headers=config.get("headers", {}),
        params=config.get("params", {}),
        api_key=api_key,
        response_path=config.get("response_path"),
        allow_local_demo_feed=bool(config.get("local_demo_feed", False)),
    )


async def execute_ingestion_job(session: AsyncSession, job: IngestionJob) -> IngestionJob:
    source = await session.get(CTISource, job.source_id)
    if source is None:
        raise ValueError(f"Source {job.source_id} does not exist")
    if not source.is_active:
        raise ValueError(f"Source {source.id} is inactive")

    source_type_val = _source_type_value(source.source_type)
    job.status = IngestionJobStatus.RUNNING
    job.started_at = datetime.now(timezone.utc)
    await session.commit()

    is_demo_source = bool((source.configuration or {}).get("local_demo_feed"))
    graph_client = None
    new_demo_document_ids: set[UUID] = set()
    demo_pipeline_totals = {
        "attack_mappings": 0,
        "semantic_chunks": 0,
        "graph_nodes": 0,
        "graph_relationships": 0,
    }
    try:
        if is_demo_source:
            settings = get_settings()
            graph_client = Neo4jClient(
                settings.neo4j_uri,
                settings.neo4j_user,
                settings.neo4j_password,
                settings.neo4j_database,
            )
            graph_client.verify_connectivity()
            from app.vector_store.factory import get_semantic_index

            await asyncio.to_thread(get_semantic_index().ensure_collection)
        logger.info("Executing ingestion job %s for source %s (%s)", job.id, source.name, source_type_val)
        connector = build_connector(SourceType(source_type_val), build_connector_config(source))
        logger.info("Starting connector.collect()...")
        records = await connector.collect()
        logger.info("Connector returned %d records", len(records))
        job.records_seen = len(records)
        job.records_created = 0
        for i, record in enumerate(records):
            if i % 10 == 0:
                logger.info("Processing record %d/%d (%s)...", i, len(records), record.external_id)
            existing = await session.scalar(
                select(RawSourceRecord).where(
                    RawSourceRecord.source_id == source.id,
                    RawSourceRecord.external_id == record.external_id,
                )
            )
            if existing is not None:
                continue
            record = record.model_copy(
                update={
                    "metadata": {
                        **record.metadata,
                        "source_type": source_type_val,
                    }
                }
            )
            normalized = normalize_record(record)
            raw = RawSourceRecord(
                source_id=source.id,
                ingestion_job_id=job.id,
                external_id=record.external_id,
                content_hash=hashlib.sha256(
                    serialize_raw_content(record).encode("utf-8")
                ).hexdigest(),
                source_url=record.source_url,
                retrieved_at=record.collected_at,
                payload=record.payload,
                raw_content=serialize_raw_content(record),
                content_type=record.content_type,
            )
            session.add(raw)
            await session.flush()
            duplicate_of = await session.scalar(
                select(CTIDocument).where(CTIDocument.content_hash == normalized.content_hash).limit(1)
            )
            if duplicate_of is not None:
                relationship, similarity = "exact", 100.0
            else:
                candidate_result = await session.execute(
                    select(CTIDocument).order_by(CTIDocument.created_at.desc()).limit(100)
                )
                duplicate_of, relationship, similarity = find_duplicate(
                    normalized, list(candidate_result.scalars())
                )
            canonical_key = hashlib.sha256(
                f"{source.id}:{record.external_id}".encode("utf-8")
            ).hexdigest()
            document = CTIDocument(
                    source_id=source.id,
                    raw_record_id=raw.id,
                    canonical_key=canonical_key,
                    title=normalized.original_title,
                    normalized_content=normalized.normalized_text,
                    original_title=normalized.original_title,
                    normalized_title=normalized.normalized_title,
                    normalized_text=normalized.normalized_text,
                    original_url=normalized.original_url,
                    content_hash=normalized.content_hash,
                    document_type=normalized.document_type,
                    normalization_status=(
                        "duplicate" if duplicate_of is not None else "normalized"
                    ),
                    duplicate_of_document_id=duplicate_of.id if duplicate_of else None,
                    duplicate_relationship=relationship,
                    document_status=(
                        DocumentStatus.NORMALIZED
                        if duplicate_of is None
                        else DocumentStatus.INGESTED
                    ),
                    published_at=normalized.published_at,
                    retrieved_at=normalized.collected_at,
                    language=normalized.language,
                    provenance={
                        **normalized.provenance,
                        "source_vendor": source.name.casefold(),
                        "connector_source_type": source_type_val,
                        **({"fictional_demo_source": True} if is_demo_source else {}),
                        **(
                            {
                                "duplicate_of_document_id": str(duplicate_of.id),
                                "duplicate_similarity": similarity,
                            }
                            if duplicate_of
                            else {}
                        ),
                    },
                )
            session.add(document)
            await session.flush()
            await persist_document_entities(
                session,
                document,
                text=normalized.normalized_text,
                structured_metadata=record.payload,
            )
            apply_classification(document, classify_document(document))
            await prioritize_document(session, document)
            job.records_created += 1
            if is_demo_source:
                if graph_client is None:
                    raise RuntimeError("Neo4j client was not initialized for a demo source")
                pipeline_result = await process_demo_document(
                    session,
                    document,
                    record.payload,
                    graph_client,
                )
                new_demo_document_ids.add(document.id)
                for key, value in pipeline_result.items():
                    demo_pipeline_totals[key] += value
        if is_demo_source and new_demo_document_ids:
            job.job_metadata = {
                **(job.job_metadata or {}),
                "demo_pipeline": demo_pipeline_totals,
            }
        job.status = IngestionJobStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        job.error_message = None
        await session.commit()
    except Exception as exc:
        await session.rollback()
        job = await session.get(IngestionJob, job.id) or job
        job.status = IngestionJobStatus.FAILED
        job.completed_at = datetime.now(timezone.utc)
        job.error_message = str(exc)[:4000]
        await session.commit()
        logger.exception("Ingestion job %s failed", job.id)
        if isinstance(exc, ConnectorError):
            raise
        raise
    finally:
        if graph_client is not None:
            graph_client.close()
    return job


async def create_and_run_job(
    session: AsyncSession, source_id: UUID, *, run_now: bool = True
) -> IngestionJob:
    source = await session.get(CTISource, source_id)
    if source is None:
        raise ValueError(f"Source {source_id} does not exist")
    job = IngestionJob(
        source_id=source_id,
        status=IngestionJobStatus.PENDING,
        job_metadata={"manual": run_now},
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    if run_now:
        return await execute_ingestion_job(session, job)
    return job
