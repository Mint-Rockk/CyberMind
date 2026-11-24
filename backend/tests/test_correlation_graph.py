import pytest
from datetime import datetime, timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base, get_db_session
from app.db.models import (
    CorrelationJob,
    CorrelationJobStatus,
    CorrelationRecord,
    CTIDocument,
    CTISource,
    DocumentEntityAssociation,
    DocumentStatus,
    ExtractedEntity,
    SourceType,
)
from app.main import app


@pytest.fixture()
def client_and_factory():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_session():
        async with session_factory() as session:
            yield session

    import asyncio

    async def setup():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    async def teardown():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.drop_all)
        await engine.dispose()

    asyncio.run(setup())
    app.dependency_overrides[get_db_session] = override_session
    with TestClient(app) as test_client:
        yield test_client, session_factory
    app.dependency_overrides.clear()
    asyncio.run(teardown())


@pytest.mark.asyncio
async def test_latest_completed_graph_empty_state_when_no_job(client_and_factory) -> None:
    client, _ = client_and_factory
    response = client.get("/api/v1/correlations/jobs/latest-completed/graph")
    assert response.status_code == 200
    data = response.json()
    assert data["job"] is None
    assert data["summary"]["job_status"] == "no_job"
    assert data["nodes"] == []
    assert data["edges"] == []


@pytest.mark.asyncio
async def test_latest_completed_graph_scopes_to_latest_job_and_distinguishes_related(client_and_factory) -> None:
    client, session_factory = client_and_factory

    async with session_factory() as session:
        source = CTISource(
            id=uuid4(),
            name="Source Alpha",
            source_type=SourceType.OSINT,
            base_url="https://example.com",
            configuration={},
        )
        session.add(source)

        doc1 = CTIDocument(
            id=uuid4(),
            source_id=source.id,
            canonical_key="key-1",
            title="Advisory 101: Ransomware Campaign",
            normalized_content="Actor APT28 deployed malware X.",
            document_status=DocumentStatus.NORMALIZED,
            published_at=datetime.now(timezone.utc),
            retrieved_at=datetime.now(timezone.utc),
        )
        doc2 = CTIDocument(
            id=uuid4(),
            source_id=source.id,
            canonical_key="key-2",
            title="Advisory 102: Phishing Surge",
            normalized_content="Malware X observed in spearphishing.",
            document_status=DocumentStatus.NORMALIZED,
            published_at=datetime.now(timezone.utc),
            retrieved_at=datetime.now(timezone.utc),
        )
        doc3 = CTIDocument(
            id=uuid4(),
            source_id=source.id,
            canonical_key="key-3",
            title="Advisory 103: Unrelated Incident",
            normalized_content="DDoS attack on DNS.",
            document_status=DocumentStatus.NORMALIZED,
            published_at=datetime.now(timezone.utc),
            retrieved_at=datetime.now(timezone.utc),
        )
        session.add_all([doc1, doc2, doc3])

        entity = ExtractedEntity(
            id=uuid4(),
            entity_type="threat_actor",
            canonical_name="APT28",
            normalized_value="apt28",
            confidence=0.95,
        )
        session.add(entity)

        assoc1 = DocumentEntityAssociation(
            id=uuid4(),
            document_id=doc1.id,
            entity_id=entity.id,
            mention_text="APT28",
            confidence=0.9,
        )
        session.add(assoc1)

        # Job 1 (old)
        old_job = CorrelationJob(
            id=uuid4(),
            status=CorrelationJobStatus.COMPLETED,
            threshold=0.35,
            pairs_considered=1,
            correlations_created=1,
            predictor_type="evidence_aware_random_forest",
            predictor_version="f1-improvement-v3",
            completed_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        )
        session.add(old_job)

        old_record = CorrelationRecord(
            id=uuid4(),
            first_document_id=doc1.id,
            second_document_id=doc3.id,
            temporal_similarity=0.1,
            entity_relationship_similarity=0.1,
            behavioural_similarity=0.1,
            attack_technique_similarity=0.1,
            semantic_embedding_similarity=0.1,
            knowledge_graph_relationship_similarity=0.1,
            correlation_probability=0.2,
            prediction_threshold=0.35,
            predicted_relationship_label="unrelated",
            predictor_type="evidence_aware_random_forest",
            predictor_version="f1-improvement-v3",
            feature_schema_version="correlation-features-v1",
            evidence_and_explanation={"correlation_job_id": str(old_job.id)},
        )
        session.add(old_record)

        # Job 2 (latest)
        latest_job = CorrelationJob(
            id=uuid4(),
            status=CorrelationJobStatus.COMPLETED,
            threshold=0.35,
            pairs_considered=2,
            correlations_created=2,
            predictor_type="evidence_aware_random_forest",
            predictor_version="f1-improvement-v3",
            completed_at=datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc),
        )
        session.add(latest_job)

        record_related = CorrelationRecord(
            id=uuid4(),
            first_document_id=doc1.id,
            second_document_id=doc2.id,
            temporal_similarity=0.8,
            entity_relationship_similarity=0.7,
            behavioural_similarity=0.6,
            attack_technique_similarity=0.5,
            semantic_embedding_similarity=0.75,
            knowledge_graph_relationship_similarity=0.6,
            correlation_probability=0.75,
            prediction_threshold=0.35,
            predicted_relationship_label="related",
            predictor_type="evidence_aware_random_forest",
            predictor_version="f1-improvement-v3",
            feature_schema_version="correlation-features-v1",
            evidence_and_explanation={"correlation_job_id": str(latest_job.id)},
        )
        record_unrelated = CorrelationRecord(
            id=uuid4(),
            first_document_id=doc2.id,
            second_document_id=doc3.id,
            temporal_similarity=0.1,
            entity_relationship_similarity=0.0,
            behavioural_similarity=0.1,
            attack_technique_similarity=0.1,
            semantic_embedding_similarity=0.2,
            knowledge_graph_relationship_similarity=0.1,
            correlation_probability=0.15,
            prediction_threshold=0.35,
            predicted_relationship_label="unrelated",
            predictor_type="evidence_aware_random_forest",
            predictor_version="f1-improvement-v3",
            feature_schema_version="correlation-features-v1",
            evidence_and_explanation={"correlation_job_id": str(latest_job.id)},
        )
        session.add_all([record_related, record_unrelated])
        await session.commit()

    # 1. Fetch latest graph (default: includes all evaluated pairs from latest run)
    resp = client.get("/api/v1/correlations/jobs/latest-completed/graph")
    assert resp.status_code == 200
    data = resp.json()

    assert data["job"]["id"] == str(latest_job.id)
    assert data["summary"]["job_id"] == str(latest_job.id)
    assert data["summary"]["related_count"] == 1
    assert data["summary"]["unrelated_count"] == 1

    # Check nodes
    report_nodes = [n for n in data["nodes"] if n["type"] == "report"]
    entity_nodes = [n for n in data["nodes"] if n["type"] == "entity"]
    assert len(report_nodes) == 3
    assert len(entity_nodes) == 1
    assert entity_nodes[0]["label"] == "APT28"
    assert entity_nodes[0]["entity_type"] == "threat_actor"

    # Check edges: 2 correlation edges + 1 report-to-entity edge
    corr_edges = [e for e in data["edges"] if e["type"] == "correlation"]
    ent_edges = [e for e in data["edges"] if e["type"] == "has_entity"]
    assert len(corr_edges) == 2
    assert len(ent_edges) == 1

    # Old job record must NOT be in correlation edges
    edge_ids = {e["id"] for e in corr_edges}
    assert str(old_record.id) not in edge_ids
    assert str(record_related.id) in edge_ids
    assert str(record_unrelated.id) in edge_ids

    # 2. Test filter: only_related=true
    resp_related = client.get("/api/v1/correlations/jobs/latest-completed/graph?only_related=true")
    assert resp_related.status_code == 200
    data_related = resp_related.json()
    corr_edges_related = [e for e in data_related["edges"] if e["type"] == "correlation"]
    assert len(corr_edges_related) == 1
    assert corr_edges_related[0]["id"] == str(record_related.id)
    assert corr_edges_related[0]["is_related"] is True
    assert corr_edges_related[0]["probability"] == 0.75

    # 3. Test fetch by specific job_id
    resp_job1 = client.get(f"/api/v1/correlations/jobs/{old_job.id}/graph")
    assert resp_job1.status_code == 200
    data_job1 = resp_job1.json()
    assert data_job1["job"]["id"] == str(old_job.id)
    assert data_job1["summary"]["job_id"] == str(old_job.id)
    corr_edges_job1 = [e for e in data_job1["edges"] if e["type"] == "correlation"]
    assert len(corr_edges_job1) == 1
    assert corr_edges_job1[0]["id"] == str(old_record.id)

    # 4. Non-existent job returns 404
    missing_id = uuid4()
    resp_404 = client.get(f"/api/v1/correlations/jobs/{missing_id}/graph")
    assert resp_404.status_code == 404

    # 5. Verify graph endpoint does not create new jobs or mutate DB
    async with session_factory() as session:
        jobs = (await session.execute(select(CorrelationJob))).scalars().all()
        assert len(jobs) == 2
