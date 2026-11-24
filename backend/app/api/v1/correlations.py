import logging
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.correlation.orchestration import run_correlation_job
from app.core.config import get_settings
from app.db.base import get_db_session
from app.db.models import (
    CampaignDocumentAssociation,
    CorrelationJob,
    CorrelationJobStatus,
    CorrelationRecord,
    CTIDocument,
    CTISource,
    DocumentEntityAssociation,
    ExtractedEntity,
)
from app.db.schemas import (
    CorrelationGraphEdge,
    CorrelationGraphNode,
    CorrelationGraphResponse,
    CorrelationGraphSummary,
    CorrelationJobCreate,
    CorrelationJobResponse,
    CorrelationRecordResponse,
)
from app.graph.client import Neo4jClient
from app.ml.correlation.base import PredictorUnavailableError
from app.ml.correlation.predictor_factory import create_predictor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/correlations", tags=["correlations"])


@router.post("/jobs", response_model=CorrelationJobResponse, status_code=201)
async def create_correlation_job(
    request: CorrelationJobCreate,
    session: AsyncSession = Depends(get_db_session),
):
    threshold = (
        float(create_predictor().get_model_metadata().get(
            "threshold", get_settings().correlation_threshold
        ))
        if request.threshold is None
        else request.threshold
    )
    job = CorrelationJob(
        status=CorrelationJobStatus.PENDING,
        threshold=threshold,
        document_id=request.document_id,
        campaign_id=request.campaign_id,
        rerun=request.rerun,
    )
    session.add(job)
    await session.flush()
    try:
        await run_correlation_job(session, job)
        await session.commit()
    except PredictorUnavailableError as exc:
        await session.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValueError as exc:
        await session.commit()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return job


@router.get("/jobs", response_model=list[CorrelationJobResponse])
async def list_correlation_jobs(
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db_session),
):
    result = await session.execute(
        select(CorrelationJob)
        .order_by(CorrelationJob.requested_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/jobs/latest-completed", response_model=CorrelationJobResponse | None)
async def get_latest_completed_correlation_job(
    session: AsyncSession = Depends(get_db_session),
):
    result = await session.execute(
        select(CorrelationJob)
        .where(CorrelationJob.status == CorrelationJobStatus.COMPLETED)
        .order_by(CorrelationJob.completed_at.desc(), CorrelationJob.requested_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def _build_correlation_graph(
    session: AsyncSession,
    job: CorrelationJob | None,
    *,
    only_related: bool = False,
    include_entities: bool = True,
    min_probability: float | None = None,
) -> CorrelationGraphResponse:
    if job is None:
        return CorrelationGraphResponse(
            job=None,
            summary=CorrelationGraphSummary(
                job_status="no_job",
                report_count=0,
                entity_count=0,
                related_count=0,
                unrelated_count=0,
            ),
            nodes=[],
            edges=[],
        )

    # Fetch correlation records for this job
    query = select(CorrelationRecord).where(
        CorrelationRecord.evidence_and_explanation["correlation_job_id"].as_string() == str(job.id)
    )
    if min_probability is not None:
        query = query.where(CorrelationRecord.correlation_probability >= min_probability)
    records = (await session.execute(query)).scalars().all()

    related_count = sum(1 for r in records if r.predicted_relationship_label == "related")
    unrelated_count = len(records) - related_count

    edge_records = [r for r in records if r.predicted_relationship_label == "related"] if only_related else records

    doc_ids: set[UUID] = set()
    for r in records:
        doc_ids.add(r.first_document_id)
        doc_ids.add(r.second_document_id)

    docs: list[CTIDocument] = []
    if doc_ids:
        docs = (
            await session.execute(
                select(CTIDocument)
                .where(CTIDocument.id.in_(doc_ids))
                .options(
                    selectinload(CTIDocument.source),
                    selectinload(CTIDocument.entity_associations).selectinload(
                        DocumentEntityAssociation.entity
                    ),
                )
            )
        ).scalars().all()

    nodes: list[CorrelationGraphNode] = []
    edges: list[CorrelationGraphEdge] = []
    seen_entities: dict[UUID, ExtractedEntity] = {}

    for doc in docs:
        source_name = doc.source.name if doc.source else "Unknown Source"
        nodes.append(
            CorrelationGraphNode(
                id=f"report:{doc.id}",
                type="report",
                label=doc.title or f"Report {str(doc.id)[:8]}",
                source_id=str(doc.source_id) if doc.source_id else None,
                source_name=source_name,
                published_at=doc.published_at or doc.retrieved_at,
                attributes={
                    "document_id": str(doc.id),
                    "canonical_key": doc.canonical_key,
                },
            )
        )
        if include_entities:
            for assoc in doc.entity_associations:
                entity = assoc.entity
                if entity is not None and str(entity.entity_type) != "campaign":
                    if entity.id not in seen_entities:
                        seen_entities[entity.id] = entity
                        nodes.append(
                            CorrelationGraphNode(
                                id=f"entity:{entity.id}",
                                type="entity",
                                label=entity.canonical_name or entity.normalized_value,
                                entity_type=str(entity.entity_type),
                                canonical_name=entity.canonical_name,
                                attributes={
                                    "entity_id": str(entity.id),
                                    "normalized_value": entity.normalized_value,
                                },
                            )
                        )
                    edges.append(
                        CorrelationGraphEdge(
                            id=f"rep-ent:{doc.id}:{entity.id}",
                            source=f"report:{doc.id}",
                            target=f"entity:{entity.id}",
                            type="has_entity",
                            label=str(entity.entity_type),
                            evidence={
                                "mention_text": assoc.mention_text,
                                "confidence": assoc.confidence,
                                "extraction_method": assoc.extraction_method,
                            },
                        )
                    )

    for r in edge_records:
        edges.append(
            CorrelationGraphEdge(
                id=str(r.id),
                source=f"report:{r.first_document_id}",
                target=f"report:{r.second_document_id}",
                type="correlation",
                label=r.predicted_relationship_label,
                probability=r.correlation_probability,
                prediction_threshold=r.prediction_threshold,
                is_related=r.predicted_relationship_label == "related",
                predictor_type=r.predictor_type,
                predictor_version=r.predictor_version,
                feature_similarities={
                    "temporal_similarity": r.temporal_similarity,
                    "entity_relationship_similarity": r.entity_relationship_similarity,
                    "behavioural_similarity": r.behavioural_similarity,
                    "attack_technique_similarity": r.attack_technique_similarity,
                    "semantic_embedding_similarity": r.semantic_embedding_similarity,
                    "knowledge_graph_relationship_similarity": r.knowledge_graph_relationship_similarity,
                },
                evidence=r.evidence_and_explanation or {},
            )
        )

    job_status = job.status.value if hasattr(job.status, "value") else str(job.status)
    summary = CorrelationGraphSummary(
        job_id=job.id,
        job_status=job_status,
        requested_at=job.requested_at,
        completed_at=job.completed_at,
        threshold=job.threshold,
        pairs_considered=job.pairs_considered,
        correlations_created=job.correlations_created,
        related_count=related_count,
        unrelated_count=unrelated_count,
        report_count=len(docs),
        entity_count=len(seen_entities),
        predictor_type=job.predictor_type,
        predictor_version=job.predictor_version,
    )

    return CorrelationGraphResponse(
        job=CorrelationJobResponse.model_validate(job),
        summary=summary,
        nodes=nodes,
        edges=edges,
    )


@router.get("/jobs/latest-completed/graph", response_model=CorrelationGraphResponse)
async def get_latest_completed_correlation_graph(
    only_related: bool = Query(default=False),
    include_entities: bool = Query(default=True),
    min_probability: float | None = Query(default=None, ge=0, le=1),
    session: AsyncSession = Depends(get_db_session),
):
    result = await session.execute(
        select(CorrelationJob)
        .where(CorrelationJob.status == CorrelationJobStatus.COMPLETED)
        .order_by(CorrelationJob.completed_at.desc(), CorrelationJob.requested_at.desc())
        .limit(1)
    )
    job = result.scalar_one_or_none()
    return await _build_correlation_graph(
        session,
        job,
        only_related=only_related,
        include_entities=include_entities,
        min_probability=min_probability,
    )


@router.get("/jobs/{job_id}/graph", response_model=CorrelationGraphResponse)
async def get_correlation_job_graph(
    job_id: UUID,
    only_related: bool = Query(default=False),
    include_entities: bool = Query(default=True),
    min_probability: float | None = Query(default=None, ge=0, le=1),
    session: AsyncSession = Depends(get_db_session),
):
    job = await session.get(CorrelationJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Correlation job not found")
    return await _build_correlation_graph(
        session,
        job,
        only_related=only_related,
        include_entities=include_entities,
        min_probability=min_probability,
    )


@router.post("/jobs/{job_id}/rerun", response_model=CorrelationJobResponse, status_code=201)
async def rerun_correlation_job(
    job_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    original = await session.get(CorrelationJob, job_id)
    if original is None:
        raise HTTPException(status_code=404, detail="Correlation job not found")
    rerun = CorrelationJob(
        status=CorrelationJobStatus.PENDING,
        threshold=original.threshold,
        document_id=original.document_id,
        campaign_id=original.campaign_id,
        rerun=True,
    )
    session.add(rerun)
    await session.flush()
    try:
        await run_correlation_job(session, rerun)
        await session.commit()
    except (PredictorUnavailableError, ValueError) as exc:
        await session.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return rerun


@router.get("", response_model=list[CorrelationRecordResponse])
async def list_correlations(
    job_id: UUID | None = None,
    min_probability: float | None = Query(default=None, ge=0, le=1),
    max_probability: float | None = Query(default=None, ge=0, le=1),
    created_after: datetime | None = None,
    created_before: datetime | None = None,
    document_id: UUID | None = None,
    campaign_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    session: AsyncSession = Depends(get_db_session),
):
    query = select(CorrelationRecord).order_by(CorrelationRecord.created_at.desc())
    if job_id is not None:
        query = query.where(
            CorrelationRecord.evidence_and_explanation["correlation_job_id"].as_string() == str(job_id)
        )
    if min_probability is not None:
        query = query.where(CorrelationRecord.correlation_probability >= min_probability)
    if max_probability is not None:
        query = query.where(CorrelationRecord.correlation_probability <= max_probability)
    if created_after:
        query = query.where(CorrelationRecord.created_at >= created_after)
    if created_before:
        query = query.where(CorrelationRecord.created_at <= created_before)
    if document_id:
        query = query.where(
            or_(
                CorrelationRecord.first_document_id == document_id,
                CorrelationRecord.second_document_id == document_id,
            )
        )
    if campaign_id:
        query = query.join(
            CampaignDocumentAssociation,
            or_(
                CampaignDocumentAssociation.document_id == CorrelationRecord.first_document_id,
                CampaignDocumentAssociation.document_id == CorrelationRecord.second_document_id,
            ),
        ).where(CampaignDocumentAssociation.campaign_id == campaign_id)
    result = await session.execute(query.limit(limit))
    return result.scalars().unique().all()


@router.delete("", status_code=200)
@router.post("/clear", status_code=200)
async def clear_correlations(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, object]:
    record_count = (await session.scalar(select(func.count()).select_from(CorrelationRecord))) or 0
    job_count = (await session.scalar(select(func.count()).select_from(CorrelationJob))) or 0
    await session.execute(delete(CorrelationRecord))
    await session.execute(delete(CorrelationJob))
    await session.commit()
    settings = get_settings()
    try:
        client = Neo4jClient(
            settings.neo4j_uri,
            settings.neo4j_user,
            settings.neo4j_password,
            settings.neo4j_database,
        )
        try:
            client.run(
                "MATCH ()-[relationship:RELATED_TO {relationship_origin: 'system_inferred'}]->() "
                "DELETE relationship"
            )
        finally:
            client.close()
    except Exception as exc:
        logger.warning("Neo4j correlation relationship cleanup skipped: %s", exc)
    return {
        "status": "cleared",
        "records_cleared": int(record_count),
        "jobs_cleared": int(job_count),
    }


@router.get("/{correlation_id}", response_model=CorrelationRecordResponse)
async def get_correlation(
    correlation_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    record = await session.get(CorrelationRecord, correlation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Correlation not found")
    return record
