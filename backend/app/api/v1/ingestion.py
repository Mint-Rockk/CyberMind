from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.base import ConnectorError
from app.db.base import get_db_session
from app.db.models import IngestionJob
from app.db.schemas import IngestionJobCreate, IngestionJobResponse
from app.ingestion.service import create_and_run_job

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post("/jobs", response_model=IngestionJobResponse, status_code=status.HTTP_201_CREATED)
async def create_ingestion_job(
    payload: IngestionJobCreate, session: AsyncSession = Depends(get_db_session)
):
    try:
        return await create_and_run_job(session, payload.source_id, run_now=payload.run_now)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ConnectorError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/jobs", response_model=list[IngestionJobResponse])
async def list_ingestion_jobs(session: AsyncSession = Depends(get_db_session)):
    result = await session.execute(select(IngestionJob).order_by(IngestionJob.created_at.desc()))
    return result.scalars().all()


@router.get("/jobs/{job_id}", response_model=IngestionJobResponse)
async def get_ingestion_job(job_id: UUID, session: AsyncSession = Depends(get_db_session)):
    job = await session.get(IngestionJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Ingestion job not found")
    return job
