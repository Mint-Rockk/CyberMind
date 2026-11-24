from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.campaigns.service import (
    clear_campaign_candidates,
    discover_campaigns,
    set_campaign_decision,
)
from app.core.config import get_settings
from app.db.base import get_db_session
from app.db.models import (
    Campaign,
    CampaignDocumentAssociation,
    CampaignHistory,
    CampaignStatus,
    CorrelationJob,
    CorrelationJobStatus,
    CTIDocument,
)
from app.db.schemas import (
    CampaignClearResponse,
    CampaignCreate,
    CampaignDecisionRequest,
    CampaignDetailResponse,
    CampaignDiscoveryRequest,
    CampaignResponse,
)
from app.graph.client import GraphUnavailableError, Neo4jClient
from app.graph.sync import GraphSynchronizer

router = APIRouter(prefix="/campaigns", tags=["campaigns"])


def _campaign_detail_options():
    return (
        selectinload(Campaign.document_associations)
        .selectinload(CampaignDocumentAssociation.document)
        .selectinload(CTIDocument.source),
        selectinload(Campaign.history),
    )


async def _sync_campaign_reports(
    session: AsyncSession,
    campaign_ids: list[UUID],
) -> None:
    settings = get_settings()
    client = None
    try:
        client = Neo4jClient(
            settings.neo4j_uri,
            settings.neo4j_user,
            settings.neo4j_password,
            settings.neo4j_database,
        )
        result = await session.execute(
            select(CampaignDocumentAssociation.document_id).where(
                CampaignDocumentAssociation.campaign_id.in_(campaign_ids)
            )
        )
        document_ids = sorted(set(result.scalars().all()), key=str)
        synchronizer = GraphSynchronizer(
            client,
            retries=settings.neo4j_sync_retries,
        )
        for document_id in document_ids:
            await synchronizer.sync_document(session, document_id)
        await session.commit()
    except ValueError as exc:
        await session.commit()
        raise HTTPException(
            status_code=503,
            detail="Campaigns were saved, but Neo4j synchronization is misconfigured.",
        ) from exc
    except GraphUnavailableError as exc:
        await session.commit()
        raise HTTPException(
            status_code=503,
            detail="Campaigns were saved, but Neo4j synchronization failed.",
        ) from exc
    finally:
        if client is not None:
            client.close()


@router.post("", response_model=CampaignResponse, status_code=201)
async def create_campaign(
    request: CampaignCreate,
    session: AsyncSession = Depends(get_db_session),
):
    campaign = Campaign(**request.model_dump())
    session.add(campaign)
    await session.flush()
    session.add(
        CampaignHistory(
            campaign_id=campaign.id,
            event_type="created",
            new_status=campaign.status,
            event_evidence={"relationship_origin": "analyst_created"},
        )
    )
    await session.commit()
    await session.refresh(campaign)
    return campaign


@router.post("/discover", response_model=list[CampaignDetailResponse])
async def discover_campaigns_route(
    request: CampaignDiscoveryRequest,
    session: AsyncSession = Depends(get_db_session),
):
    latest_job = await session.scalar(
        select(CorrelationJob)
        .where(CorrelationJob.status == CorrelationJobStatus.COMPLETED)
        .order_by(CorrelationJob.completed_at.desc(), CorrelationJob.requested_at.desc())
        .limit(1)
    )
    if latest_job is None:
        raise HTTPException(
            status_code=400,
            detail="No completed correlation job found. Run a correlation job first.",
        )
    if request.job_id is not None and request.job_id != latest_job.id:
        raise HTTPException(
            status_code=400,
            detail=f"The requested correlation job {request.job_id} is not the latest completed correlation run ({latest_job.id}).",
        )
    try:
        campaigns = await discover_campaigns(
            session,
            probability_threshold=request.probability_threshold,
            minimum_similarity=request.minimum_similarity,
            job_id=latest_job.id,
        )
        await session.commit()
    except ValueError as exc:
        await session.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not campaigns:
        return []
    await _sync_campaign_reports(
        session,
        [campaign.id for campaign in campaigns],
    )
    result = await session.execute(
        select(Campaign)
        .options(*_campaign_detail_options())
        .where(Campaign.id.in_([campaign.id for campaign in campaigns]))
    )
    return result.scalars().unique().all()


@router.delete("", response_model=CampaignClearResponse)
@router.post("/clear", response_model=CampaignClearResponse)
async def clear_campaigns_route(
    job_id: UUID | None = None,
    session: AsyncSession = Depends(get_db_session),
):
    count = await clear_campaign_candidates(session, job_id=job_id)
    return CampaignClearResponse(
        status="cleared",
        candidates_cleared=count,
        job_id=str(job_id) if job_id else None,
    )


@router.get("", response_model=list[CampaignResponse])
async def list_campaigns(
    status: CampaignStatus | None = None,
    job_id: UUID | None = None,
    all_runs: bool = False,
    limit: int = Query(default=100, ge=1, le=300),
    session: AsyncSession = Depends(get_db_session),
):
    query = select(Campaign).order_by(Campaign.updated_at.desc())
    if status:
        query = query.where(Campaign.status == status)
    result = await session.execute(query)
    campaigns = list(result.scalars().all())

    if not all_runs:
        target_job_id = job_id
        if target_job_id is None:
            latest_job = await session.scalar(
                select(CorrelationJob)
                .where(CorrelationJob.status == CorrelationJobStatus.COMPLETED)
                .order_by(CorrelationJob.completed_at.desc(), CorrelationJob.requested_at.desc())
                .limit(1)
            )
            target_job_id = latest_job.id if latest_job else None

        filtered = []
        for c in campaigns:
            is_synthetic = c.evidence.get("classification") == "synthetic_demo_ground_truth"
            is_decided = c.status in (CampaignStatus.CONFIRMED, CampaignStatus.REJECTED)
            if is_synthetic or is_decided:
                filtered.append(c)
                continue
            if target_job_id is not None:
                c_job_id = c.evidence.get("correlation_job_id") or (
                    c.evidence.get("discovery_thresholds", {}).get("correlation_job_id")
                )
                if c_job_id == str(target_job_id):
                    filtered.append(c)
        campaigns = filtered[:limit]
    else:
        campaigns = campaigns[:limit]

    return campaigns


@router.get("/{campaign_id}", response_model=CampaignDetailResponse)
async def get_campaign(
    campaign_id: UUID,
    session: AsyncSession = Depends(get_db_session),
):
    result = await session.execute(
        select(Campaign)
        .options(*_campaign_detail_options())
        .where(Campaign.id == campaign_id)
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return campaign


@router.post("/{campaign_id}/decision", response_model=CampaignDetailResponse)
async def decide_campaign(
    campaign_id: UUID,
    request: CampaignDecisionRequest,
    session: AsyncSession = Depends(get_db_session),
):
    result = await session.execute(
        select(Campaign)
        .options(*_campaign_detail_options())
        .where(Campaign.id == campaign_id)
    )
    campaign = result.scalar_one_or_none()
    if campaign is None:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if request.decision not in {CampaignStatus.CONFIRMED, CampaignStatus.REJECTED}:
        raise HTTPException(status_code=422, detail="Decision must be confirmed or rejected")
    if request.relationship_origin not in {"analyst_confirmed", "source_confirmed"}:
        raise HTTPException(status_code=422, detail="Unsupported relationship origin")
    await set_campaign_decision(
        session,
        campaign,
        status=request.decision,
        comments=request.comments,
        actor_id=request.actor_id,
        relationship_origin=request.relationship_origin,
    )
    await session.commit()
    await session.refresh(campaign)
    return campaign
