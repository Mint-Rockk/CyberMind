from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import get_db_session
from app.db.models import CTIDocument
from app.db.schemas import CTIDocumentResponse
from app.classification.service import (
    apply_classification,
    classify_document,
    prioritize_document,
)

router = APIRouter(prefix="/documents", tags=["documents"])


@router.get("", response_model=list[CTIDocumentResponse])
async def list_documents(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    document_type: str | None = Query(default=None),
    session: AsyncSession = Depends(get_db_session),
):
    query = select(CTIDocument).order_by(CTIDocument.created_at.desc()).offset(offset).limit(limit)
    if document_type:
        query = query.where(CTIDocument.document_type == document_type)
    result = await session.execute(query)
    return result.scalars().all()


@router.post("/{document_id}/classify", response_model=CTIDocumentResponse)
async def classify_document_route(
    document_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    document = await session.get(CTIDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    apply_classification(document, classify_document(document))
    await session.commit()
    await session.refresh(document)
    return document


@router.post("/{document_id}/prioritize", response_model=CTIDocumentResponse)
async def prioritize_document_route(
    document_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    document = await session.get(CTIDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    await prioritize_document(session, document)
    await session.commit()
    await session.refresh(document)
    return document


@router.get("/{document_id}", response_model=CTIDocumentResponse)
async def get_document(
    document_id: UUID, session: AsyncSession = Depends(get_db_session)
):
    document = await session.get(CTIDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document
