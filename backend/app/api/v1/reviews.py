from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_analyst
from app.db.base import get_db_session
from app.db.models import (
    AnalystReview,
    Campaign,
    CampaignStatus,
    CorrelationRecord,
    Investigation,
    User,
)
from app.db.schemas import AnalystReviewResponse, ReviewQueueItem, ReviewRequest
from app.review.service import apply_review

router = APIRouter(prefix="/reviews", tags=["reviews"])


@router.get("/queue", response_model=list[ReviewQueueItem])
async def review_queue(
    limit: int = Query(default=100, ge=1, le=300),
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_analyst),
) -> list[ReviewQueueItem]:
    items: list[ReviewQueueItem] = []
    campaigns = (
        await session.execute(
            select(Campaign)
            .where(Campaign.status == CampaignStatus.CANDIDATE)
            .order_by(Campaign.updated_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    items.extend(
        ReviewQueueItem(
            target_type="campaign",
            target_id=item.id,
            title=item.name,
            status=str(item.status),
            updated_at=item.updated_at,
        )
        for item in campaigns
    )
    correlations = (
        await session.execute(
            select(CorrelationRecord)
            .order_by(CorrelationRecord.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    items.extend(
        ReviewQueueItem(
            target_type="correlation",
            target_id=item.id,
            title=f"{item.first_document_id} ↔ {item.second_document_id}",
            status=item.predicted_relationship_label,
            updated_at=item.created_at,
        )
        for item in correlations
    )
    investigations = (
        await session.execute(
            select(Investigation)
            .where(Investigation.status == "open")
            .order_by(Investigation.created_at.desc())
            .limit(limit)
        )
    ).scalars().all()
    items.extend(
        ReviewQueueItem(
            target_type="investigation",
            target_id=item.id,
            title=item.title,
            status=str(item.status),
            updated_at=item.updated_at,
        )
        for item in investigations
    )
    return sorted(items, key=lambda item: item.updated_at, reverse=True)[:limit]


@router.post("", response_model=AnalystReviewResponse, status_code=201)
async def create_review(
    request: ReviewRequest,
    session: AsyncSession = Depends(get_db_session),
    analyst: User = Depends(get_current_analyst),
) -> AnalystReview:
    try:
        review = await apply_review(
            session,
            analyst,
            target_type=request.target_type,
            target_id=request.target_id,
            decision=request.decision,
            reason=request.reason,
            evidence_reference=request.evidence_reference,
            correction=request.correction,
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    await session.commit()
    await session.refresh(review)
    return review


@router.get("", response_model=list[AnalystReviewResponse])
async def list_reviews(
    target_type: str | None = None,
    target_id: UUID | None = None,
    limit: int = Query(default=100, ge=1, le=300),
    session: AsyncSession = Depends(get_db_session),
    _: User = Depends(get_current_analyst),
) -> list[AnalystReview]:
    query = select(AnalystReview).order_by(AnalystReview.created_at.desc()).limit(limit)
    if target_type:
        query = query.where(AnalystReview.target_type == target_type)
    if target_id:
        query = query.where(AnalystReview.target_id == target_id)
    result = await session.execute(query)
    return list(result.scalars().all())
