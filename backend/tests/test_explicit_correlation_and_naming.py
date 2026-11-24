import pytest
from datetime import datetime, timezone
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base, get_db_session
from app.db.models import (
    Campaign,
    CampaignHistory,
    CampaignStatus,
    CorrelationJob,
    CorrelationJobStatus,
    CorrelationRecord,
    CTIDocument,
    CTISource,
    DocumentEntityAssociation,
    ExtractedEntity,
    SourceType,
)
from app.ingestion.service import execute_ingestion_job
from app.db.models import IngestionJob, IngestionJobStatus
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
async def test_page_reads_refreshes_and_ingestion_do_not_invoke_correlation_or_naming(client_and_factory) -> None:
    client, session_factory = client_and_factory
    now = datetime.now(timezone.utc)

    # 1. Seed a source and documents directly
    async with session_factory() as session:
        source = CTISource(
            name="Demo Desk",
            source_type=SourceType.RESEARCH,
            base_url="https://example.test/feed",
            configuration={"local_demo_feed": True},
        )
        session.add(source)
        await session.flush()
        doc1 = CTIDocument(
            source_id=source.id,
            canonical_key="doc-1",
            title="Doc 1",
            normalized_content="Actor Moth Lantern targeted server.",
            normalized_text="Actor Moth Lantern targeted server.",
            retrieved_at=now,
            document_status="normalized",
            provenance={},
        )
        doc2 = CTIDocument(
            source_id=source.id,
            canonical_key="doc-2",
            title="Doc 2",
            normalized_content="Actor Moth Lantern invoice lure.",
            normalized_text="Actor Moth Lantern invoice lure.",
            retrieved_at=now,
            document_status="normalized",
            provenance={},
        )
        session.add_all([doc1, doc2])
        await session.commit()

    # 2. Page/API reads and refreshes do NOT invoke correlation or campaign naming
    res1 = client.get("/api/v1/correlations")
    assert res1.status_code == 200
    assert res1.json() == []

    res2 = client.get("/api/v1/correlations/jobs")
    assert res2.status_code == 200
    assert res2.json() == []

    res3 = client.get("/api/v1/campaigns")
    assert res3.status_code == 200
    assert res3.json() == []

    res4 = client.get("/api/v1/dashboard/summary")
    assert res4.status_code == 200
    assert res4.json()["correlations"] == 0
    assert res4.json()["campaigns"] == 0

    # 3. Verify no correlation jobs or records were created by any of those reads
    async with session_factory() as session:
        corr_jobs = (await session.execute(select(CorrelationJob))).scalars().all()
        corr_records = (await session.execute(select(CorrelationRecord))).scalars().all()
        campaigns = (await session.execute(select(Campaign))).scalars().all()
        assert len(corr_jobs) == 0
        assert len(corr_records) == 0
        assert len(campaigns) == 0


def test_clicking_run_correlation_job_invokes_exactly_one_run(client_and_factory) -> None:
    client, _ = client_and_factory

    # 1. Trigger correlation job explicitly
    res = client.post("/api/v1/correlations/jobs", json={"threshold": 0.5})
    assert res.status_code == 201
    job = res.json()
    assert job["status"] == "completed"
    job_id = job["id"]

    # 2. Verify only 1 job exists
    jobs_res = client.get("/api/v1/correlations/jobs")
    assert jobs_res.status_code == 200
    assert len(jobs_res.json()) == 1
    assert jobs_res.json()[0]["id"] == job_id

    # 3. Querying correlations for that job returns its records
    records_res = client.get(f"/api/v1/correlations?job_id={job_id}")
    assert records_res.status_code == 200


@pytest.mark.asyncio
async def test_clear_correlations_clears_only_correlation_results_and_preserves_other_data(client_and_factory) -> None:
    client, session_factory = client_and_factory
    now = datetime.now(timezone.utc)

    # 1. Seed document, source, campaign, campaign history, and correlation record/job
    async with session_factory() as session:
        source = CTISource(
            name="Preserved Source",
            source_type=SourceType.RESEARCH,
            base_url="https://example.test/source",
            configuration={},
        )
        session.add(source)
        await session.flush()
        doc = CTIDocument(
            source_id=source.id,
            canonical_key="preserved-doc",
            title="Preserved Document",
            normalized_content="Content",
            normalized_text="Content",
            retrieved_at=now,
            document_status="normalized",
            provenance={},
        )
        session.add(doc)
        await session.flush()

        campaign = Campaign(
            name="Preserved Campaign",
            status=CampaignStatus.CONFIRMED,
            description="Analyst confirmed campaign",
            confidence=0.95,
            evidence={"classification": "analyst_confirmed"},
        )
        session.add(campaign)
        await session.flush()
        history = CampaignHistory(
            campaign_id=campaign.id,
            event_type="analyst_decision",
            previous_status=CampaignStatus.CANDIDATE,
            new_status=CampaignStatus.CONFIRMED,
            event_evidence={"decision": "confirmed"},
            occurred_at=now,
        )
        session.add(history)

        corr_job = CorrelationJob(
            status=CorrelationJobStatus.COMPLETED,
            threshold=0.35,
            rerun=False,
        )
        session.add(corr_job)
        await session.flush()

        corr_record = CorrelationRecord(
            first_document_id=doc.id,
            second_document_id=doc.id,
            temporal_similarity=1.0,
            entity_relationship_similarity=1.0,
            behavioural_similarity=0.5,
            attack_technique_similarity=0.5,
            semantic_embedding_similarity=0.5,
            knowledge_graph_relationship_similarity=0.5,
            correlation_probability=0.88,
            prediction_threshold=0.35,
            predicted_relationship_label="related",
            predictor_type="baseline_heuristic",
            predictor_version="v1",
            feature_schema_version="v1",
            evidence_and_explanation={"correlation_job_id": str(corr_job.id)},
        )
        session.add(corr_record)
        await session.commit()

    # 2. Invoke Clear previous correlations endpoint
    clear_res = client.delete("/api/v1/correlations")
    assert clear_res.status_code == 200
    data = clear_res.json()
    assert data["status"] == "cleared"
    assert data["records_cleared"] == 1
    assert data["jobs_cleared"] == 1

    # 3. Active correlation view is now empty
    assert client.get("/api/v1/correlations").json() == []
    assert client.get("/api/v1/correlations/jobs").json() == []

    # 4. Verify sources, documents, campaigns, and campaign history are 100% PRESERVED
    async with session_factory() as session:
        sources = (await session.execute(select(CTISource))).scalars().all()
        assert len(sources) == 1
        assert sources[0].name == "Preserved Source"

        docs = (await session.execute(select(CTIDocument))).scalars().all()
        assert len(docs) == 1
        assert docs[0].canonical_key == "preserved-doc"

        camps = (await session.execute(select(Campaign))).scalars().all()
        assert len(camps) == 1
        assert camps[0].name == "Preserved Campaign"
        assert camps[0].status == CampaignStatus.CONFIRMED

        histories = (await session.execute(select(CampaignHistory))).scalars().all()
        assert len(histories) == 1
        assert histories[0].event_type == "analyst_decision"


@pytest.mark.asyncio
async def test_subsequent_correlation_run_displays_only_its_own_results(client_and_factory) -> None:
    client, session_factory = client_and_factory
    now = datetime.now(timezone.utc)

    # 1. Seed two documents with an entity to allow correlation
    async with session_factory() as session:
        source = CTISource(
            name="Run Source",
            source_type=SourceType.RESEARCH,
            base_url="https://example.test/run",
            configuration={},
        )
        session.add(source)
        await session.flush()
        d1 = CTIDocument(
            source_id=source.id,
            canonical_key="d1",
            title="D1",
            normalized_content="Threat actor Moth Lantern reported in logistics sector.",
            normalized_text="Threat actor Moth Lantern reported in logistics sector.",
            retrieved_at=now,
            document_status="normalized",
            provenance={},
        )
        d2 = CTIDocument(
            source_id=source.id,
            canonical_key="d2",
            title="D2",
            normalized_content="Threat actor Moth Lantern reported in banking sector.",
            normalized_text="Threat actor Moth Lantern reported in banking sector.",
            retrieved_at=now,
            document_status="normalized",
            provenance={},
        )
        entity = ExtractedEntity(
            entity_type="threat_actor",
            canonical_name="Moth Lantern",
            normalized_value="moth lantern",
            attributes={},
        )
        session.add_all([d1, d2, entity])
        await session.flush()
        session.add_all([
            DocumentEntityAssociation(document_id=d1.id, entity_id=entity.id),
            DocumentEntityAssociation(document_id=d2.id, entity_id=entity.id),
        ])
        await session.commit()

    # 2. Clear correlations
    clear_res = client.delete("/api/v1/correlations")
    assert clear_res.status_code == 200

    # 3. Run job 1
    job1_res = client.post("/api/v1/correlations/jobs", json={"threshold": 0.35})
    assert job1_res.status_code == 201
    job1_id = job1_res.json()["id"]

    # 4. Filter by job1_id returns only job1's records
    records_job1 = client.get(f"/api/v1/correlations?job_id={job1_id}").json()
    assert all(r["evidence_and_explanation"].get("correlation_job_id") == job1_id for r in records_job1)


def test_correlation_and_naming_errors_are_visible(client_and_factory) -> None:
    client, _ = client_and_factory

    # 1. Invalid threshold returns 422 with detail
    res_invalid_corr = client.post("/api/v1/correlations/jobs", json={"threshold": 2.5})
    assert res_invalid_corr.status_code == 422
    assert "detail" in res_invalid_corr.json()

    # 2. Invalid discovery threshold returns 422 with detail
    res_invalid_disc = client.post("/api/v1/campaigns/discover", json={"probability_threshold": -0.5})
    assert res_invalid_disc.status_code == 422
    assert "detail" in res_invalid_disc.json()


@pytest.mark.asyncio
async def test_naming_uses_only_latest_completed_job_and_rejects_stale_or_missing_runs(client_and_factory) -> None:
    client, session_factory = client_and_factory
    now = datetime.now(timezone.utc)

    # 1. Calling discover when no correlation job exists fails with clear 400 error
    res_no_job = client.post("/api/v1/campaigns/discover", json={"probability_threshold": 0.35})
    assert res_no_job.status_code == 400
    assert "No completed correlation job found" in res_no_job.json()["detail"]

    # 2. Seed documents for Run 1
    async with session_factory() as session:
        source = CTISource(name="Source 1", source_type=SourceType.RESEARCH, base_url="https://test1", configuration={})
        session.add(source)
        await session.flush()
        d1 = CTIDocument(source_id=source.id, canonical_key="d1", title="D1", normalized_content="Actor Alpha targeted logistics.", normalized_text="Actor Alpha targeted logistics.", retrieved_at=now, document_status="normalized", provenance={})
        d2 = CTIDocument(source_id=source.id, canonical_key="d2", title="D2", normalized_content="Actor Alpha targeted financial.", normalized_text="Actor Alpha targeted financial.", retrieved_at=now, document_status="normalized", provenance={})
        e1 = ExtractedEntity(entity_type="threat_actor", canonical_name="Alpha", normalized_value="alpha", attributes={})
        session.add_all([d1, d2, e1])
        await session.flush()
        session.add_all([
            DocumentEntityAssociation(document_id=d1.id, entity_id=e1.id),
            DocumentEntityAssociation(document_id=d2.id, entity_id=e1.id),
        ])
        await session.commit()

    # 3. Execute Run 1
    job1_res = client.post("/api/v1/correlations/jobs", json={"threshold": 0.35})
    assert job1_res.status_code == 201
    job1_id = job1_res.json()["id"]

    # Check latest completed endpoint
    latest_res = client.get("/api/v1/correlations/jobs/latest-completed")
    assert latest_res.status_code == 200
    assert latest_res.json()["id"] == job1_id

    # 4. Discover for Run 1 succeeds
    disc1 = client.post("/api/v1/campaigns/discover", json={"job_id": job1_id, "probability_threshold": 0.1})
    assert disc1.status_code == 200
    assert len(disc1.json()) == 1
    c1 = disc1.json()[0]
    assert c1["evidence"]["correlation_job_id"] == job1_id

    # 5. Execute Run 2 (with new threshold)
    job2_res = client.post("/api/v1/correlations/jobs", json={"threshold": 0.40})
    assert job2_res.status_code == 201
    job2_id = job2_res.json()["id"]
    assert job2_id != job1_id

    # Now latest completed is job2
    latest2 = client.get("/api/v1/correlations/jobs/latest-completed").json()
    assert latest2["id"] == job2_id

    # Attempting to name with stale job1_id is rejected
    stale_disc = client.post("/api/v1/campaigns/discover", json={"job_id": job1_id})
    assert stale_disc.status_code == 400
    assert "not the latest completed correlation run" in stale_disc.json()["detail"]

    # Attempting to name with random non-existent UUID is rejected
    fake_id = str(uuid4())
    fake_disc = client.post("/api/v1/campaigns/discover", json={"job_id": fake_id})
    assert fake_disc.status_code == 400
    assert "not the latest completed correlation run" in fake_disc.json()["detail"]


@pytest.mark.asyncio
async def test_active_campaigns_view_scopes_to_latest_run_and_clear_preserves_other_data(client_and_factory) -> None:
    client, session_factory = client_and_factory
    now = datetime.now(timezone.utc)

    # 1. Seed synthetic demo campaign and analyst-confirmed campaign
    async with session_factory() as session:
        synth = Campaign(
            name="Synthetic Demo Campaign",
            status=CampaignStatus.CANDIDATE,
            evidence={"classification": "synthetic_demo_ground_truth"},
        )
        conf = Campaign(
            name="Analyst Confirmed Campaign",
            status=CampaignStatus.CONFIRMED,
            evidence={"relationship_origin": "analyst_confirmed"},
        )
        source = CTISource(name="Source S", source_type=SourceType.RESEARCH, base_url="https://test-s", configuration={})
        session.add_all([synth, conf, source])
        await session.flush()
        d1 = CTIDocument(source_id=source.id, canonical_key="doc-s1", title="S1", normalized_content="Actor Gamma detected.", normalized_text="Actor Gamma detected.", retrieved_at=now, document_status="normalized", provenance={})
        d2 = CTIDocument(source_id=source.id, canonical_key="doc-s2", title="S2", normalized_content="Actor Gamma active.", normalized_text="Actor Gamma active.", retrieved_at=now, document_status="normalized", provenance={})
        e1 = ExtractedEntity(entity_type="threat_actor", canonical_name="Gamma", normalized_value="gamma", attributes={})
        session.add_all([d1, d2, e1])
        await session.flush()
        session.add_all([
            DocumentEntityAssociation(document_id=d1.id, entity_id=e1.id),
            DocumentEntityAssociation(document_id=d2.id, entity_id=e1.id),
        ])
        await session.commit()

    # 2. Run Job 1 and discover campaigns
    job1_id = client.post("/api/v1/correlations/jobs", json={"threshold": 0.35}).json()["id"]
    disc1 = client.post("/api/v1/campaigns/discover", json={"job_id": job1_id, "probability_threshold": 0.1}).json()
    assert len(disc1) == 1
    c1_name = disc1[0]["name"]

    # Active campaigns list shows synthetic, confirmed, and Job 1 candidate
    active1 = client.get("/api/v1/campaigns").json()
    active1_names = [c["name"] for c in active1]
    assert "Synthetic Demo Campaign" in active1_names
    assert "Analyst Confirmed Campaign" in active1_names
    assert c1_name in active1_names

    # 3. Start and complete Job 2
    job2_id = client.post("/api/v1/correlations/jobs", json={"threshold": 0.35}).json()["id"]

    # Before naming Job 2: Job 1 candidate disappears from the active view!
    active_pre_name = client.get("/api/v1/campaigns").json()
    active_pre_names = [c["name"] for c in active_pre_name]
    assert "Synthetic Demo Campaign" in active_pre_names
    assert "Analyst Confirmed Campaign" in active_pre_names
    assert c1_name not in active_pre_names

    # But Job 1 candidate is still in history (all_runs=true)
    all_runs_camps = client.get("/api/v1/campaigns?all_runs=true").json()
    all_runs_names = [c["name"] for c in all_runs_camps]
    assert c1_name in all_runs_names

    # 4. Run naming for Job 2: creates candidate for Job 2
    disc2 = client.post("/api/v1/campaigns/discover", json={"job_id": job2_id, "probability_threshold": 0.1}).json()
    assert len(disc2) == 1
    c2 = disc2[0]
    assert c2["evidence"]["correlation_job_id"] == job2_id

    # Active view now shows Job 2 candidate and NOT Job 1 candidate
    active2 = client.get("/api/v1/campaigns").json()
    active2_names = [c["name"] for c in active2]
    assert "Synthetic Demo Campaign" in active2_names
    assert "Analyst Confirmed Campaign" in active2_names
    assert c2["name"] in active2_names

    # 5. Idempotency: repeating naming for Job 2 returns the same campaign without creating duplicates
    disc2_repeat = client.post("/api/v1/campaigns/discover", json={"job_id": job2_id, "probability_threshold": 0.1}).json()
    assert len(disc2_repeat) == 1
    assert disc2_repeat[0]["id"] == c2["id"]

    # 6. Clear campaign names: clears only candidate campaigns
    clear_res = client.delete("/api/v1/campaigns")
    assert clear_res.status_code == 200
    assert clear_res.json()["candidates_cleared"] >= 1

    # Active view now only has synthetic demo and analyst confirmed campaigns
    active_after_clear = client.get("/api/v1/campaigns").json()
    after_clear_names = [c["name"] for c in active_after_clear]
    assert "Synthetic Demo Campaign" in after_clear_names
    assert "Analyst Confirmed Campaign" in after_clear_names
    assert c2["name"] not in after_clear_names

    # Documents and correlations are 100% PRESERVED
    async with session_factory() as session:
        docs = (await session.execute(select(CTIDocument))).scalars().all()
        assert len(docs) == 2
        corrs = (await session.execute(select(CorrelationRecord))).scalars().all()
        assert len(corrs) >= 1
