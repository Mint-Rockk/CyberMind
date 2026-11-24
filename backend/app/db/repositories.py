from collections.abc import Sequence
from typing import Any, TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import Base
from app.db.models import (
    CTIDocument,
    CTISource,
    CorrelationRecord,
    EntityType,
    ExtractedEntity,
)

ModelT = TypeVar("ModelT", bound=Base)


async def get_by_id(session: AsyncSession, model: type[ModelT], entity_id: UUID) -> ModelT | None:
    return await session.get(model, entity_id)


async def list_entities(
    session: AsyncSession,
    model: type[ModelT],
    *,
    limit: int = 100,
    offset: int = 0,
) -> Sequence[ModelT]:
    result = await session.execute(select(model).offset(offset).limit(limit))
    return result.scalars().all()


async def create_entity(session: AsyncSession, entity: ModelT) -> ModelT:
    session.add(entity)
    await session.commit()
    await session.refresh(entity)
    return entity


async def get_source_by_name(session: AsyncSession, name: str) -> CTISource | None:
    result = await session.execute(select(CTISource).where(CTISource.name == name))
    return result.scalar_one_or_none()


async def get_document_by_canonical_key(
    session: AsyncSession, canonical_key: str
) -> CTIDocument | None:
    result = await session.execute(
        select(CTIDocument).where(CTIDocument.canonical_key == canonical_key)
    )
    return result.scalar_one_or_none()


async def list_correlations_for_document(
    session: AsyncSession, document_id: UUID, *, limit: int = 100
) -> Sequence[CorrelationRecord]:
    result = await session.execute(
        select(CorrelationRecord)
        .where(
            (CorrelationRecord.first_document_id == document_id)
            | (CorrelationRecord.second_document_id == document_id)
        )
        .order_by(CorrelationRecord.correlation_probability.desc())
        .limit(limit)
    )
    return result.scalars().all()


async def get_entity_by_value(
    session: AsyncSession, entity_type: EntityType, normalized_value: str
) -> ExtractedEntity | None:
    result = await session.execute(
        select(ExtractedEntity).where(
            ExtractedEntity.entity_type == entity_type.value,
            ExtractedEntity.normalized_value == normalized_value,
        )
    )
    return result.scalar_one_or_none()


async def list_entities_for_document(
    session: AsyncSession, document_id: UUID, *, limit: int = 100
):
    from app.db.models import DocumentEntityAssociation

    result = await session.execute(
        select(DocumentEntityAssociation)
        .where(DocumentEntityAssociation.document_id == document_id)
        .order_by(DocumentEntityAssociation.extracted_at)
        .limit(limit)
    )
    return result.scalars().all()
