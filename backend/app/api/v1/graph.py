from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.base import get_db_session
from app.db.schemas import GraphStatusResponse, GraphSyncResponse
from app.graph.client import GraphUnavailableError, Neo4jClient
from app.graph.service import GraphQueryService
from app.graph.sync import GraphSynchronizer

router = APIRouter(prefix="/graph", tags=["graph"])


def _client() -> Neo4jClient:
    settings = get_settings()
    return Neo4jClient(
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password,
        settings.neo4j_database,
    )


@router.get("/status", response_model=GraphStatusResponse)
def graph_status() -> GraphStatusResponse:
    try:
        client = _client()
    except ValueError as exc:
        return GraphStatusResponse(status="invalid_configuration", database=get_settings().neo4j_database, detail=str(exc))
    try:
        return GraphQueryService(client).status()
    finally:
        client.close()


@router.get("/search")
def search_graph(
    query: str = Query(min_length=1, max_length=200),
    label: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
) -> list[dict]:
    client = _client()
    try:
        return GraphQueryService(client).search(query, label, limit)
    except GraphUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Neo4j is unavailable") from exc
    finally:
        client.close()


@router.get("/neighborhood/{stable_node_id}")
def graph_neighborhood(
    stable_node_id: str,
    limit: int = Query(default=100, ge=1, le=300),
) -> list[dict]:
    client = _client()
    try:
        return GraphQueryService(client).neighborhood(stable_node_id, limit)
    except GraphUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Neo4j is unavailable") from exc
    finally:
        client.close()


@router.get("/campaigns/{campaign_id}")
def campaign_subgraph(
    campaign_id: UUID,
    limit: int = Query(default=200, ge=1, le=500),
) -> list[dict]:
    client = _client()
    try:
        return GraphQueryService(client).campaign_subgraph(str(campaign_id), limit)
    except GraphUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Neo4j is unavailable") from exc
    finally:
        client.close()


@router.get("/reports/{document_id}/context")
def report_context(
    document_id: UUID,
    limit: int = Query(default=100, ge=1, le=300),
) -> list[dict]:
    client = _client()
    try:
        return GraphQueryService(client).report_context(str(document_id), limit)
    except GraphUnavailableError as exc:
        raise HTTPException(status_code=503, detail="Neo4j is unavailable") from exc
    finally:
        client.close()


@router.post("/sync/documents/{document_id}", response_model=GraphSyncResponse)
async def sync_document(
    document_id: UUID,
    session: AsyncSession = Depends(get_db_session),
) -> GraphSyncResponse:
    client = _client()
    try:
        result = await GraphSynchronizer(
            client,
            retries=get_settings().neo4j_sync_retries,
        ).sync_document(session, document_id)
        await session.commit()
        return result
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except GraphUnavailableError as exc:
        await session.commit()
        raise HTTPException(status_code=503, detail="Neo4j synchronization failed") from exc
    finally:
        client.close()
