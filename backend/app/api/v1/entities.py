from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.base import get_db_session
from app.db.models import (
    DocumentEntityAssociation,
    EntityType,
    ExtractedEntity,
)
from app.db.schemas import (
    DocumentEntityAssociationResponse,
    ExtractedEntityDetailResponse,
    ExtractedEntityResponse,
)

router = APIRouter(prefix="/entities", tags=["entities"])


@router.get("", response_model=list[ExtractedEntityResponse])
async def list_entities(
    entity_type: EntityType | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db_session),
):
    query = select(ExtractedEntity).order_by(ExtractedEntity.created_at.desc())
    if entity_type:
        query = query.where(ExtractedEntity.entity_type == entity_type.value)
    if search:
        query = query.where(ExtractedEntity.normalized_value.ilike(f"%{search}%"))
    result = await session.execute(query.offset(offset).limit(limit))
    return result.scalars().all()


@router.get(
    "/documents/{document_id}",
    response_model=list[DocumentEntityAssociationResponse],
)
async def list_document_entities(
    document_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    result = await session.execute(
        select(DocumentEntityAssociation)
        .where(DocumentEntityAssociation.document_id == document_id)
        .order_by(DocumentEntityAssociation.extracted_at)
    )
    return result.scalars().all()


@router.get("/{entity_id}", response_model=ExtractedEntityDetailResponse)
async def get_entity(
    entity_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    result = await session.execute(
        select(ExtractedEntity)
        .options(selectinload(ExtractedEntity.document_associations))
        .where(ExtractedEntity.id == entity_id)
    )
    entity = result.scalar_one_or_none()
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")
    return entity
