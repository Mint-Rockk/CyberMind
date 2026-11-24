from collections.abc import AsyncGenerator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base, get_db_session
from app.main import app


@pytest.fixture()
def client():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session() -> AsyncGenerator[AsyncSession, None]:
        async with session_factory() as session:
            yield session

    async def setup():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    async def teardown():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    import asyncio

    asyncio.run(setup())
    app.dependency_overrides[get_db_session] = override_session
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    asyncio.run(teardown())


def test_source_and_ingestion_job_lifecycle(client: TestClient) -> None:
    documents = client.get("/api/v1/documents")
    assert documents.status_code == 200
    assert documents.json() == []
    entities = client.get("/api/v1/entities")
    assert entities.status_code == 200
    assert entities.json() == []

    source_response = client.post(
        "/api/v1/sources",
        json={
            "name": "Fixture Public RSS",
            "source_type": "rss",
            "base_url": "https://example.test/feed.xml",
            "configuration": {"schedule_minutes": 60},
        },
    )
    assert source_response.status_code == 201
    source = source_response.json()
    assert source["health_status"] == "unknown"

    sources = client.get("/api/v1/sources")
    assert sources.status_code == 200
    assert sources.json()[0]["name"] == "Fixture Public RSS"

    job_response = client.post(
        "/api/v1/ingestion/jobs",
        json={"source_id": source["id"], "run_now": False},
    )
    assert job_response.status_code == 201
    assert job_response.json()["status"] == "pending"

    jobs = client.get("/api/v1/ingestion/jobs")
    assert jobs.status_code == 200
    assert len(jobs.json()) == 1

    correlation_job = client.post(
        "/api/v1/correlations/jobs",
        json={"threshold": 0.7},
    )
    assert correlation_job.status_code == 201
    assert correlation_job.json()["status"] == "completed"
    assert correlation_job.json()["predictor_type"] in {
        "baseline_heuristic",
        "evidence_aware_random_forest",
    }
    assert client.get("/api/v1/correlations/jobs").json()[0]["pairs_considered"] == 0
    assert client.get("/api/v1/correlations").status_code == 200

    campaign_response = client.post(
        "/api/v1/campaigns",
        json={"name": "Fixture Candidate", "description": "Fixture only"},
    )
    assert campaign_response.status_code == 201
    campaign_id = campaign_response.json()["id"]
    detail = client.get(f"/api/v1/campaigns/{campaign_id}")
    assert detail.status_code == 200
    assert detail.json()["history"][0]["event_type"] == "created"
    decision = client.post(
        f"/api/v1/campaigns/{campaign_id}/decision",
        json={"decision": "rejected", "comments": "Fixture is not intelligence."},
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "rejected"
    assert decision.json()["history"][-1]["event_type"] == "analyst_decision"

    update = client.put(
        f"/api/v1/sources/{source['id']}",
        json={"is_active": False, "name": "Disabled Fixture RSS"},
    )
    assert update.status_code == 200
    assert update.json()["health_status"] == "inactive"
