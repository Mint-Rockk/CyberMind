from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import DBAPIError

from app.db.base import get_db_session
from app.db.models import Campaign, CorrelationRecord, CTIDocument, CTISource, Investigation

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary")
async def dashboard_summary(
    session: AsyncSession = Depends(get_db_session),
) -> dict[str, int]:
    async def count(model) -> int:
        return int(await session.scalar(select(func.count()).select_from(model)) or 0)

    try:
        return {
            "sources": await count(CTISource),
            "documents": await count(CTIDocument),
            "investigations": await count(Investigation),
            "campaigns": await count(Campaign),
            "correlations": await count(CorrelationRecord),
        }
    except DBAPIError as exc:
        raise HTTPException(status_code=503, detail="Database is unavailable") from exc
