from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.correlation.candidates import CandidateDocument, generate_candidate_pairs
from app.correlation.orchestration import run_correlation_job
from app.db.base import Base
from app.db.models import (
    CorrelationJob,
    CorrelationJobStatus,
    CorrelationRecord,
    CTIDocument,
    CTISource,
    DocumentEntityAssociation,
    ExtractedEntity,
    SourceType,
)
from app.ml.correlation.baseline_predictor import BaselinePredictor


def test_candidate_generation_uses_indexed_signals_not_unrestricted_pairs() -> None:
    first, second, unrelated = CandidateDocument(
        document_id=UUID("00000000-0000-0000-0000-000000000001"),
        entities=frozenset({"apt28"}),
    ), CandidateDocument(
        document_id=UUID("00000000-0000-0000-0000-000000000002"),
        entities=frozenset({"apt28"}),
    ), CandidateDocument(
        document_id=UUID("00000000-0000-0000-0000-000000000003"),
        entities=frozenset({"lazarus"}),
    )

    candidates = generate_candidate_pairs([first, second, unrelated])

    assert len(candidates) == 1
    assert "shared_entity" in candidates[0].reasons


def test_candidate_generation_accepts_semantic_and_graph_indexes() -> None:
    first_id = UUID("00000000-0000-0000-0000-000000000011")
    second_id = UUID("00000000-0000-0000-0000-000000000012")
    candidates = generate_candidate_pairs(
        [
            CandidateDocument(document_id=first_id),
            CandidateDocument(document_id=second_id),
        ],
        semantic_neighbors={first_id: {second_id}},
        graph_neighbors={first_id: {second_id}},
    )

    assert len(candidates) == 1
    assert candidates[0].reasons == {"semantic_retrieval", "knowledge_graph_relationship"}


def test_targeted_candidate_generation_omits_old_to_old_pairs() -> None:
    target_id = UUID("00000000-0000-0000-0000-000000000021")
    documents = [
        CandidateDocument(
            document_id=UUID(f"00000000-0000-0000-0000-{index:012d}"),
            entities=frozenset({"shared actor"}),
        )
        for index in range(21, 25)
    ]
    candidates = generate_candidate_pairs(
        documents,
        target_document_ids={target_id},
    )
    assert len(candidates) == 3
    assert all(target_id in {item.first_document_id, item.second_document_id} for item in candidates)


@pytest.mark.asyncio
async def test_baseline_orchestration_persists_features_evidence_and_metadata() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime.now(timezone.utc)
    async with factory() as session:
        source = CTISource(
            name="Correlation Fixture Source",
            source_type=SourceType.RESEARCH,
            base_url="https://example.test/correlation",
            configuration={},
        )
        session.add(source)
        await session.flush()
        first = CTIDocument(
            source_id=source.id,
            canonical_key="correlation-first",
            title="APT28 activity",
            normalized_content="APT28 phishing activity",
            normalized_text="APT28 phishing activity",
            retrieved_at=now,
            published_at=now,
            document_status="normalized",
            provenance={},
        )
        second = CTIDocument(
            source_id=source.id,
            canonical_key="correlation-second",
            title="APT28 follow-up",
            normalized_content="APT28 phishing follow-up",
            normalized_text="APT28 phishing follow-up",
            retrieved_at=now + timedelta(hours=1),
            published_at=now,
            document_status="normalized",
            provenance={},
        )
        entity = ExtractedEntity(
            entity_type="threat_actor",
            canonical_name="APT28",
            normalized_value="apt28",
            attributes={},
        )
        session.add_all([first, second, entity])
        await session.flush()
        session.add_all([
            DocumentEntityAssociation(document_id=first.id, entity_id=entity.id),
            DocumentEntityAssociation(document_id=second.id, entity_id=entity.id),
        ])
        job = CorrelationJob(
            status=CorrelationJobStatus.PENDING,
            threshold=0.65,
            rerun=False,
        )
        session.add(job)
        await session.flush()

        await run_correlation_job(session, job, predictor=BaselinePredictor())
        await session.commit()

        record = await session.scalar(select(CorrelationRecord))
        assert record is not None
        assert record.temporal_similarity == 1.0
        assert record.entity_relationship_similarity == 1.0
        assert record.semantic_embedding_similarity == 0.5
        assert record.knowledge_graph_relationship_similarity == 0.5
        assert record.predictor_type == "baseline_heuristic"
        assert record.predicted_relationship_label == "related"
        assert record.evidence_and_explanation["missing_features"] == [
            "behavioural_similarity",
            "attack_technique_similarity",
            "semantic_embedding_similarity",
            "knowledge_graph_relationship_similarity",
        ]
        assert job.status == CorrelationJobStatus.COMPLETED
        assert job.pairs_considered == 1
        assert job.correlations_created == 1

    await engine.dispose()
