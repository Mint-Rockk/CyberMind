from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db_session
from app.db.models import CTIDocument, CTISource, IngestionJob, IngestionJobStatus
from app.db.schemas import CTISourceCreate, CTISourceResponse, CTISourceUpdate
from app.ingestion.scheduler import collection_scheduler

router = APIRouter(prefix="/sources", tags=["sources"])


async def source_response(session: AsyncSession, source: CTISource) -> CTISourceResponse:
    latest_job = await session.scalar(
        select(IngestionJob)
        .where(IngestionJob.source_id == source.id)
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    )
    last_successful_collection = await session.scalar(
        select(func.max(IngestionJob.completed_at)).where(
            IngestionJob.source_id == source.id,
            IngestionJob.status == IngestionJobStatus.COMPLETED,
        )
    )
    reports_collected = int(await session.scalar(
        select(func.count(CTIDocument.id)).where(
            CTIDocument.source_id == source.id,
            CTIDocument.normalization_status != "duplicate",
        )
    ) or 0)
    if not source.is_active:
        health_status = "inactive"
    elif latest_job is None:
        health_status = "unknown"
    elif latest_job.status == IngestionJobStatus.COMPLETED:
        health_status = "healthy"
    else:
        health_status = "error" if latest_job.status == IngestionJobStatus.FAILED else "collecting"
    return CTISourceResponse(
        id=source.id,
        name=source.name,
        source_type=source.source_type,
        base_url=source.base_url,
        reliability_score=source.reliability_score,
        is_active=source.is_active,
        terms_url=source.terms_url,
        configuration=source.configuration,
        health_status=health_status,
        last_successful_collection=last_successful_collection,
        reports_collected=reports_collected,
        created_at=source.created_at,
    )


@router.get("", response_model=list[CTISourceResponse])
async def list_sources(session: AsyncSession = Depends(get_db_session)):
    sources = (await session.execute(select(CTISource).order_by(CTISource.name))).scalars().all()
    return [await source_response(session, source) for source in sources]


@router.post("", response_model=CTISourceResponse, status_code=status.HTTP_201_CREATED)
async def create_source(
    payload: CTISourceCreate, session: AsyncSession = Depends(get_db_session)
):
    duplicate = await session.scalar(select(CTISource).where(CTISource.name == payload.name))
    if duplicate:
        raise HTTPException(status_code=409, detail="A source with this name already exists")
    source = CTISource(
        name=payload.name,
        source_type=payload.source_type,
        base_url=str(payload.base_url),
        terms_url=str(payload.terms_url) if payload.terms_url else None,
        reliability_score=payload.reliability_score,
        configuration=payload.configuration,
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    collection_scheduler.schedule_source(source)
    return await source_response(session, source)


@router.put("/{source_id}", response_model=CTISourceResponse)
async def update_source(
    source_id: UUID,
    payload: CTISourceUpdate,
    session: AsyncSession = Depends(get_db_session),
):
    source = await session.get(CTISource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    values = payload.model_dump(exclude_unset=True)
    if "base_url" in values and values["base_url"] is not None:
        values["base_url"] = str(values["base_url"])
    if "terms_url" in values and values["terms_url"] is not None:
        values["terms_url"] = str(values["terms_url"])
    for key, value in values.items():
        setattr(source, key, value)
    await session.commit()
    await session.refresh(source)
    collection_scheduler.schedule_source(source)
    return await source_response(session, source)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_source(source_id: UUID, session: AsyncSession = Depends(get_db_session)):
    source = await session.get(CTISource, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    source.is_active = False
    await session.commit()
    collection_scheduler.remove_source(source.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
