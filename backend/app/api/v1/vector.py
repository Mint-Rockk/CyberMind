from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from qdrant_client.http.exceptions import UnexpectedResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.db.base import get_db_session
from app.db.models import CTIDocument, DocumentEntityAssociation
from app.db.schemas import SemanticIndexResponse, SemanticSearchResultResponse
from app.vector_store.factory import get_semantic_index

router = APIRouter(prefix="/vector", tags=["vector"])


async def _document(session: AsyncSession, document_id: UUID) -> CTIDocument:
    result = await session.execute(
        select(CTIDocument)
        .options(
            selectinload(CTIDocument.source),
            selectinload(CTIDocument.entity_associations).selectinload(
                DocumentEntityAssociation.entity
            ),
        )
        .where(CTIDocument.id == document_id)
    )
    document = result.scalar_one_or_none()
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return document


@router.post("/documents/{document_id}/index", response_model=SemanticIndexResponse)
async def index_document(
    document_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> SemanticIndexResponse:
    document = await _document(session, document_id)
    settings = get_settings()
    try:
        chunks = get_semantic_index().index_document(
            document_id=document.id,
            text=document.normalized_text or document.normalized_content,
            source_id=document.source_id,
            source_url=document.original_url or document.source.base_url,
            title=document.normalized_title or document.title,
            collected_at=document.retrieved_at,
            published_at=document.published_at,
            document_type=document.document_type,
            source_reliability=document.source.reliability_score,
            entity_values=(
                association.entity.normalized_value
                for association in document.entity_associations
                if association.entity is not None
            ),
        )
    except (ValueError, UnexpectedResponse) as exc:
        raise HTTPException(status_code=503, detail="Semantic indexing failed") from exc
    return SemanticIndexResponse(
        document_id=document.id,
        chunks_indexed=chunks,
        collection=settings.qdrant_collection,
        embedding_model=settings.embedding_model_version,
        embedding_dimension=settings.embedding_dimension,
    )


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: UUID) -> None:
    try:
        get_semantic_index().delete_document(document_id)
    except UnexpectedResponse as exc:
        raise HTTPException(status_code=503, detail="Semantic index is unavailable") from exc


@router.get("/search", response_model=list[SemanticSearchResultResponse])
def semantic_search(
    query: str = Query(min_length=1, max_length=400),
    source_id: UUID | None = None,
    published_after: datetime | None = None,
    published_before: datetime | None = None,
    document_type: str | None = Query(default=None, max_length=64),
    entity: str | None = Query(default=None, max_length=1024),
    limit: int = Query(default=10, ge=1, le=100),
) -> list[SemanticSearchResultResponse]:
    try:
        results = get_semantic_index().search(
            query,
            source_id=source_id,
            published_after=published_after,
            published_before=published_before,
            document_type=document_type,
            entity=entity,
            limit=limit,
        )
    except (ValueError, UnexpectedResponse) as exc:
        raise HTTPException(status_code=503, detail="Semantic search is unavailable") from exc
    return [
        SemanticSearchResultResponse(
            document_id=result.document_id,
            chunk_id=result.chunk_id,
            score=result.score,
            text=result.text,
            metadata=result.metadata,
        )
        for result in results
    ]
