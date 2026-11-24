from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.base import get_db_session
from app.db.schemas import (
    EvidenceItemResponse,
    RAGRetrieveRequest,
    RAGRetrieveResponse,
)
from app.graph.client import Neo4jClient
from app.graph.service import GraphQueryService
from app.rag.service import HybridRetrievalService, RetrievalFilters
from app.vector_store.factory import get_semantic_index
from app.vector_store.qdrant import SemanticRetrievalService

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/retrieve", response_model=RAGRetrieveResponse)
async def retrieve_evidence(
    request: RAGRetrieveRequest,
    session: AsyncSession = Depends(get_db_session),
) -> RAGRetrieveResponse:
    settings = get_settings()
    graph_client = Neo4jClient(
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password,
        settings.neo4j_database,
    )
    try:
        response = await HybridRetrievalService(
            SemanticRetrievalService(get_semantic_index()),
            GraphQueryService(graph_client),
        ).retrieve(
            session,
            request.query,
            filters=RetrievalFilters(
                campaign_id=request.campaign_id,
                source_id=request.source_id,
                published_after=request.published_after,
                published_before=request.published_before,
                document_type=request.document_type,
                entity=request.entity,
                minimum_correlation_probability=request.minimum_correlation_probability,
            ),
            limit=request.limit,
        )
        return RAGRetrieveResponse(
            query=response.query,
            evidence=[
                EvidenceItemResponse(
                    evidence_id=item.evidence_id,
                    evidence_type=item.evidence_type,
                    score=item.score,
                    document_id=item.document_id,
                    document_title=item.document_title,
                    source_url=item.source_url,
                    chunk_id=item.chunk_id,
                    relevant_text=item.relevant_text,
                    publication_timestamp=item.publication_timestamp,
                    source_reliability=item.source_reliability,
                    provenance=item.provenance,
                )
                for item in response.evidence
            ],
            source_references=response.source_references,
            context=response.context,
            sufficient_evidence=response.sufficient_evidence,
            warnings=response.warnings,
        )
    finally:
        graph_client.close()


@router.get("/search", response_model=RAGRetrieveResponse)
async def search_evidence(
    query: str = Query(min_length=1, max_length=400),
    campaign_id: UUID | None = None,
    source_id: UUID | None = None,
    published_after: datetime | None = None,
    published_before: datetime | None = None,
    document_type: str | None = None,
    entity: str | None = None,
    minimum_correlation_probability: float = Query(default=0, ge=0, le=1),
    limit: int = Query(default=10, ge=1, le=100),
    session: AsyncSession = Depends(get_db_session),
) -> RAGRetrieveResponse:
    request = RAGRetrieveRequest(
        query=query,
        campaign_id=campaign_id,
        source_id=source_id,
        published_after=published_after,
        published_before=published_before,
        document_type=document_type,
        entity=entity,
        minimum_correlation_probability=minimum_correlation_probability,
        limit=limit,
    )
    return await retrieve_evidence(request, session)
