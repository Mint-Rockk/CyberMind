from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.attack.dataset import download_official_dataset
from app.attack.service import map_document
from app.db.base import get_db_session
from app.db.models import ATTACKTechnique, CTIDocument, DocumentTechniqueMapping
from app.db.schemas import (
    ATTACKMappingDetailResponse,
    ATTACKMappingRunResponse,
    ATTACKTechniqueResponse,
)

router = APIRouter(prefix="/attack", tags=["attack"])


def _mapping_response(mapping: DocumentTechniqueMapping) -> ATTACKMappingDetailResponse:
    technique = mapping.technique
    return ATTACKMappingDetailResponse(
        id=mapping.id,
        document_id=mapping.document_id,
        technique_id=mapping.technique_id,
        external_id=technique.external_id,
        name=technique.name,
        object_type=technique.object_type,
        tactic=technique.tactic,
        confidence=mapping.confidence,
        evidence=mapping.evidence,
        mapping_method=mapping.mapping_method,
        mapping_status=mapping.mapping_status,
        dataset_version=mapping.dataset_version,
    )


@router.get("/techniques", response_model=list[ATTACKTechniqueResponse])
async def list_attack_objects(
    object_type: str | None = Query(default=None),
    search: str | None = Query(default=None, min_length=1),
    limit: int = Query(default=100, ge=1, le=300),
    session: AsyncSession = Depends(get_db_session),
):
    query = select(ATTACKTechnique).order_by(ATTACKTechnique.external_id)
    if object_type:
        query = query.where(ATTACKTechnique.object_type == object_type)
    if search:
        query = query.where(ATTACKTechnique.name.ilike(f"%{search}%"))
    result = await session.execute(query.limit(limit))
    return result.scalars().all()


@router.get("/techniques/{external_id}", response_model=ATTACKTechniqueResponse)
async def get_attack_object(
    external_id: str, session: AsyncSession = Depends(get_db_session)
):
    technique = await session.scalar(
        select(ATTACKTechnique).where(ATTACKTechnique.external_id == external_id.upper())
    )
    if technique is None:
        raise HTTPException(status_code=404, detail="ATT&CK object not found")
    return technique


@router.get(
    "/documents/{document_id}/mappings",
    response_model=list[ATTACKMappingDetailResponse],
)
async def list_document_attack_mappings(
    document_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    if await session.get(CTIDocument, document_id) is None:
        raise HTTPException(status_code=404, detail="Document not found")
    result = await session.execute(
        select(DocumentTechniqueMapping)
        .options(joinedload(DocumentTechniqueMapping.technique))
        .where(DocumentTechniqueMapping.document_id == document_id)
        .order_by(DocumentTechniqueMapping.confidence.desc())
    )
    return [_mapping_response(mapping) for mapping in result.scalars().all()]


@router.post(
    "/documents/{document_id}/map",
    response_model=ATTACKMappingRunResponse,
)
async def map_document_route(
    document_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    document = await session.get(CTIDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        dataset = await download_official_dataset()
        mappings, unsupported = await map_document(session, document, dataset)
        await session.commit()
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    mapping_ids = [mapping.id for mapping in mappings]
    result = await session.execute(
        select(DocumentTechniqueMapping)
        .options(joinedload(DocumentTechniqueMapping.technique))
        .where(DocumentTechniqueMapping.id.in_(mapping_ids))
    ) if mapping_ids else None
    mapped = [_mapping_response(mapping) for mapping in result.scalars().all()] if result else []
    return ATTACKMappingRunResponse(
        dataset_version=dataset.version,
        mappings=mapped,
        unsupported_identifiers=unsupported,
    )
