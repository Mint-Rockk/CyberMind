from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.base import get_db_session
from app.db.models import Investigation
from app.db.schemas import InvestigationResponse
from app.genai.investigation import InvestigationExecutionError, run_investigation
from app.graph.client import Neo4jClient
from app.graph.service import GraphQueryService
from app.rag.service import HybridRetrievalService
from app.vector_store.factory import get_semantic_index
from app.vector_store.qdrant import SemanticRetrievalService

router = APIRouter(prefix="/investigations", tags=["investigations"])


def _retrieval_service() -> tuple[HybridRetrievalService, Neo4jClient]:
    settings = get_settings()
    graph_client = Neo4jClient(
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password,
        settings.neo4j_database,
    )
    return HybridRetrievalService(
        SemanticRetrievalService(get_semantic_index()),
        GraphQueryService(graph_client),
    ), graph_client


@router.post("/run", response_model=InvestigationResponse, status_code=201)
async def create_investigation(
    query: str = Query(min_length=1, max_length=400),
    campaign_id: UUID | None = None,
    source_id: UUID | None = None,
    document_type: str | None = None,
    entity: str | None = None,
    limit: int = Query(default=10, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> Investigation:
    retrieval, graph_client = _retrieval_service()
    try:
        investigation = await run_investigation(
            session,
            retrieval,
            query=query,
            campaign_id=campaign_id,
            source_id=source_id,
            document_type=document_type,
            entity=entity,
            limit=limit,
        )
        await session.commit()
        await session.refresh(investigation)
        return investigation
    except InvestigationExecutionError as exc:
        await session.commit()
        raise HTTPException(
            status_code=503,
            detail={
                "message": str(exc),
                "investigation_id": str(exc.investigation_id),
            },
        ) from exc
    finally:
        graph_client.close()


@router.get("", response_model=list[InvestigationResponse])
async def list_investigations(
    limit: int = Query(default=100, ge=1, le=300),
    session: AsyncSession = Depends(get_db_session),
) -> list[Investigation]:
    result = await session.execute(
        select(Investigation).order_by(Investigation.created_at.desc()).limit(limit)
    )
    return list(result.scalars().all())


@router.get("/{investigation_id}", response_model=InvestigationResponse)
async def get_investigation(
    investigation_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> Investigation:
    investigation = await session.get(Investigation, investigation_id)
    if investigation is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return investigation
