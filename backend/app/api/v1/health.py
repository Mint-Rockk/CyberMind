from datetime import datetime, timezone

from fastapi import APIRouter
from pydantic import BaseModel

from app.core.config import get_settings
from app.graph.client import Neo4jClient

router = APIRouter(tags=["system"])


class HealthResponse(BaseModel):
    status: str
    service: str
    timestamp: datetime
    neo4j: dict[str, str | None]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    settings = get_settings()
    try:
        client = Neo4jClient(
            settings.neo4j_uri,
            settings.neo4j_user,
            settings.neo4j_password,
            settings.neo4j_database,
        )
    except ValueError as exc:
        graph_health = {"status": "invalid_configuration", "database": settings.neo4j_database, "detail": str(exc)}
    else:
        try:
            health_result = client.health()
            graph_health = {
                "status": health_result.status,
                "database": health_result.database,
                "detail": health_result.detail,
            }
        finally:
            client.close()
    return HealthResponse(
        status="ok",
        service="cybermind-api",
        timestamp=datetime.now(timezone.utc),
        neo4j=graph_health,
    )
