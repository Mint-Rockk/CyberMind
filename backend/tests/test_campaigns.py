import json
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.campaigns.naming import CampaignNamingService
from app.campaigns.service import discover_campaigns, set_campaign_decision
from app.db.base import Base
from app.db.models import (
    Campaign,
    CampaignHistory,
    CampaignDocumentAssociation,
    CampaignStatus,
    CorrelationRecord,
    CTIDocument,
    CTISource,
    SourceType,
)
from app.genai.base import LLMResponse, LLMUnavailableError


def _document(source_id, key: str) -> CTIDocument:
    return CTIDocument(
        source_id=source_id,
        canonical_key=key,
        title=key,
        normalized_content=key,
        normalized_text=key,
        retrieved_at=datetime.now(timezone.utc),
        document_status="normalized",
        provenance={},
    )


def _correlation(first, second, probability: float, *, available: bool) -> CorrelationRecord:
    dimensions = {
        "entity_relationship_similarity": {
            "available": available,
            "score": 1.0 if available else 0.0,
        },
        "behavioural_similarity": {"available": False, "score": 0.5},
        "attack_technique_similarity": {"available": False, "score": 0.5},
        "semantic_embedding_similarity": {"available": False, "score": 0.5},
        "knowledge_graph_relationship_similarity": {"available": False, "score": 0.5},
    }
    return CorrelationRecord(
        first_document_id=first.id,
        second_document_id=second.id,
        temporal_similarity=1.0,
        entity_relationship_similarity=1.0 if available else 0.0,
        behavioural_similarity=0.5,
        attack_technique_similarity=0.5,
        semantic_embedding_similarity=0.5,
        knowledge_graph_relationship_similarity=0.5,
        correlation_probability=probability,
        prediction_threshold=0.65,
        predicted_relationship_label="related",
        predictor_type="baseline_heuristic",
        predictor_version=f"fixture-{uuid4()}",
        feature_schema_version="correlation-features-v1",
        evidence_and_explanation={"features": dimensions},
    )


class FixtureCampaignNamingProvider:
    def __init__(self) -> None:
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        marker = "EVIDENCE_DATA:\n"
        start = request.user_prompt.index(marker) + len(marker)
        end = request.user_prompt.index("\n\nReturn this JSON shape:", start)
        evidence = json.loads(request.user_prompt[start:end])
        correlation_id = evidence["correlation_ids"][0]
        content = {
            "name": "Moth Lantern Activity Cluster",
            "description": "A provisional cluster of related cross-source reporting.",
            "activity_summary": {
                "text": "The reports share evidence for Moth Lantern activity.",
                "evidence_ids": evidence["report_ids"],
            },
            "main_supporting_evidence": [
                {
                    "text": "The stored model prediction supports the report relationship.",
                    "evidence_ids": [correlation_id],
                }
            ],
            "grouping_rationale": {
                "text": "A direct strong saved correlation links the reports.",
                "evidence_ids": [correlation_id],
            },
            "shared_entities": evidence["shared_entities"],
            "source_names": evidence["source_names"],
            "report_ids": evidence["report_ids"],
            "contradictions_or_limitations": [],
            "analyst_review_required": True,
        }
        return LLMResponse(
            content=json.dumps(content),
            provider="fixture-provider",
            model="fixture-campaign-model",
            response_id="fixture-response",
            usage={"total_tokens": 123},
        )


class UnavailableCampaignNamingProvider:
    async def generate(self, _request):
        raise LLMUnavailableError("fixture provider unavailable")


@pytest.mark.asyncio
async def test_demo_thresholds_name_low_score_saved_pair_without_recalculating() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        source = CTISource(
            name="Campaign Demo Source",
            source_type=SourceType.RESEARCH,
            base_url="https://example.test/demo-campaigns",
            configuration={},
        )
        session.add(source)
        await session.flush()
        first, second, unrelated_first, unrelated_second = (
            _document(source.id, "demo-related-a"),
            _document(source.id, "demo-related-b"),
            _document(source.id, "demo-unrelated-a"),
            _document(source.id, "demo-unrelated-b"),
        )
        session.add_all([first, second, unrelated_first, unrelated_second])
        await session.flush()

        low_score = _correlation(first, second, 0.465, available=True)
        low_score.prediction_threshold = 0.35
        low_score.entity_relationship_similarity = 0.111
        low_score.evidence_and_explanation["features"][
            "entity_relationship_similarity"
        ]["score"] = 0.111
        low_score.evidence_and_explanation["model_evidence"] = {
            "shared_values": {
                "shared_actor": ["Moth Lantern"],
                "shared_malware": [],
                "shared_tool": [],
                "shared_technique": [],
                "shared_indicator": [],
            }
        }
        unrelated = _correlation(
            unrelated_first,
            unrelated_second,
            0.8,
            available=True,
        )
        unrelated.predicted_relationship_label = "unrelated"
        session.add_all([low_score, unrelated])
        await session.commit()

        saved_probability = low_score.correlation_probability
        provider = FixtureCampaignNamingProvider()
        discovered = await discover_campaigns(
            session,
            naming_service=CampaignNamingService(
                provider,
                model="fixture-campaign-model",
            ),
        )
        await session.commit()

        assert len(discovered) == 1
        campaign = discovered[0]
        assert campaign.evidence["supporting_report_ids"] == sorted(
            [str(first.id), str(second.id)]
        )
        assert campaign.evidence["discovery_thresholds"] == {
            "probability_threshold": 0.35,
            "minimum_similarity": 0.1,
            "profile": "demonstration_relaxed",
        }
        assert campaign.confidence == 0.465
        assert campaign.evidence["naming"]["status"] == "ai_generated"
        assert campaign.evidence["naming"]["analyst_review_required"] is True
        assert len(provider.requests) == 1
        assert low_score.correlation_probability == saved_probability

    await engine.dispose()


@pytest.mark.asyncio
async def test_changing_threshold_changes_candidate_inclusion_and_excludes_unrelated() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        source = CTISource(
            name="Threshold Test Source",
            source_type=SourceType.RESEARCH,
            base_url="https://example.test/threshold-test",
            configuration={},
        )
        session.add(source)
        await session.flush()
        doc_a1, doc_a2 = _document(source.id, "threshold-a1"), _document(source.id, "threshold-a2")
        doc_b1, doc_b2 = _document(source.id, "threshold-b1"), _document(source.id, "threshold-b2")
        doc_c1, doc_c2 = _document(source.id, "threshold-c1"), _document(source.id, "threshold-c2")
        session.add_all([doc_a1, doc_a2, doc_b1, doc_b2, doc_c1, doc_c2])
        await session.flush()

        # Moderate related pair: prob 0.50
        corr_a = _correlation(doc_a1, doc_a2, 0.50, available=True)
        corr_a.evidence_and_explanation["model_evidence"] = {
            "shared_values": {"shared_actor": ["Moth Lantern"], "shared_malware": [], "shared_tool": [], "shared_technique": [], "shared_indicator": []}
        }
        # Strong related pair: prob 0.85
        corr_b = _correlation(doc_b1, doc_b2, 0.85, available=True)
        corr_b.evidence_and_explanation["model_evidence"] = {
            "shared_values": {"shared_actor": ["Copper Finch"], "shared_malware": ["Lockglass"], "shared_tool": [], "shared_technique": [], "shared_indicator": []}
        }
        # High-probability but unrelated pair: prob 0.90, label 'unrelated'
        corr_c = _correlation(doc_c1, doc_c2, 0.90, available=True)
        corr_c.predicted_relationship_label = "unrelated"

        session.add_all([corr_a, corr_b, corr_c])
        await session.commit()

        naming_provider = FixtureCampaignNamingProvider()
        naming_service = CampaignNamingService(naming_provider, model="fixture-campaign-model")

        # 1. At relaxed threshold 0.35: both corr_a (0.50) and corr_b (0.85) qualify. corr_c is excluded.
        discovered_35 = await discover_campaigns(
            session,
            probability_threshold=0.35,
            minimum_similarity=0.1,
            naming_service=naming_service,
        )
        await session.commit()
        assert len(discovered_35) == 2
        discovered_docs_35 = {
            doc_id
            for camp in discovered_35
            for doc_id in camp.evidence["supporting_report_ids"]
        }
        assert str(doc_a1.id) in discovered_docs_35
        assert str(doc_b1.id) in discovered_docs_35
        assert str(doc_c1.id) not in discovered_docs_35
        assert str(doc_c2.id) not in discovered_docs_35

        # 2. At higher threshold 0.70: ONLY corr_b (0.85) qualifies. corr_a (0.50) is excluded.
        discovered_70 = await discover_campaigns(
            session,
            probability_threshold=0.70,
            minimum_similarity=0.1,
            naming_service=naming_service,
        )
        await session.commit()
        assert len(discovered_70) == 1
        camp_70 = discovered_70[0]
        assert camp_70.evidence["supporting_report_ids"] == sorted([str(doc_b1.id), str(doc_b2.id)])
        assert camp_70.evidence["discovery_thresholds"]["probability_threshold"] == 0.70
        assert camp_70.evidence["discovery_thresholds"]["minimum_similarity"] == 0.1

        # 3. At very high threshold 0.95: Neither qualifies. Result is empty.
        discovered_95 = await discover_campaigns(
            session,
            probability_threshold=0.95,
            minimum_similarity=0.1,
            naming_service=naming_service,
        )
        await session.commit()
        assert len(discovered_95) == 0

        # Verify underlying correlation records and labels are preserved unchanged
        refreshed_a = await session.get(CorrelationRecord, corr_a.id)
        assert refreshed_a.correlation_probability == 0.50
        assert refreshed_a.predicted_relationship_label == "related"
        refreshed_c = await session.get(CorrelationRecord, corr_c.id)
        assert refreshed_c.correlation_probability == 0.90
        assert refreshed_c.predicted_relationship_label == "unrelated"

    await engine.dispose()


@pytest.mark.asyncio
async def test_campaign_discovery_updates_and_rejects_weak_transitive_merges() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        source = CTISource(
            name="Campaign Fixture Source",
            source_type=SourceType.RESEARCH,
            base_url="https://example.test/campaigns",
            configuration={},
        )
        session.add(source)
        await session.flush()
        first, second, third = (
            _document(source.id, "campaign-a"),
            _document(source.id, "campaign-b"),
            _document(source.id, "campaign-c"),
        )
        session.add_all([first, second, third])
        await session.flush()
        session.add_all([
            _correlation(first, second, 0.9, available=True),
            _correlation(second, third, 0.88, available=True),
            _correlation(first, third, 0.9, available=False),
        ])
        await session.commit()

        campaigns = await discover_campaigns(
            session,
            naming_service=CampaignNamingService(
                UnavailableCampaignNamingProvider()
            ),
        )
        await session.commit()

        assert len(campaigns) == 2
        associations = (
            await session.execute(
                select(CampaignDocumentAssociation).where(
                    CampaignDocumentAssociation.campaign_id.in_(
                        [campaign.id for campaign in campaigns]
                    )
                )
            )
        ).scalars().all()
        memberships = [
            {
                association.document_id
                for association in associations
                if association.campaign_id == campaign.id
            }
            for campaign in campaigns
        ]
        assert {first.id, second.id} in memberships
        assert {second.id, third.id} in memberships
        assert {first.id, second.id, third.id} not in memberships
        assert all(association.association_type == "system_inferred" for association in associations)
        assert all(campaign.confidence and campaign.confidence >= 0.88 for campaign in campaigns)
        assert all(
            campaign.evidence["naming"]["status"] == "fallback"
            for campaign in campaigns
        )

        campaign = campaigns[0]
        await set_campaign_decision(
            session,
            campaign,
            status=CampaignStatus.CONFIRMED,
            comments="Confirmed against source reporting.",
            relationship_origin="source_confirmed",
        )
        await session.commit()

        refreshed = await session.get(type(campaign), campaign.id)
        assert refreshed is not None
        assert refreshed.status == CampaignStatus.CONFIRMED
        history = (
            await session.execute(
                select(CampaignHistory).where(CampaignHistory.campaign_id == campaign.id)
            )
        ).scalars().all()
        assert {event.event_type for event in history} == {"discovered", "analyst_decision"}

    await engine.dispose()


@pytest.mark.asyncio
async def test_discovery_uses_saved_evidence_redacts_labels_and_is_idempotent() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        source = CTISource(
            name="Campaign Fixture Source",
            source_type=SourceType.RESEARCH,
            base_url="https://example.test/campaigns",
            configuration={},
        )
        session.add(source)
        await session.flush()
        first, second = _document(source.id, "campaign-label-a"), _document(
            source.id, "campaign-label-b"
        )
        first.original_title = "Operation Nightfall technical note"
        first.normalized_content = "Operation Nightfall activity; Nightfall follow-up."
        second.original_title = "Operation Nightfall follow-up"
        second.normalized_content = "Additional Nightfall reporting."
        session.add_all([first, second])
        await session.flush()

        synthetic = Campaign(
            name="Operation Nightfall",
            status=CampaignStatus.CANDIDATE,
            description="Fictional demo ground truth.",
            confidence=1.0,
            evidence={
                "classification": "synthetic_demo_ground_truth",
                "not_a_model_prediction": True,
            },
        )
        session.add(synthetic)
        await session.flush()
        session.add(
            CampaignDocumentAssociation(
                campaign_id=synthetic.id,
                document_id=first.id,
                association_type="demo_ground_truth",
                association_evidence={
                    "classification": "synthetic_demo_ground_truth",
                },
            )
        )
        correlation = _correlation(first, second, 0.9, available=True)
        correlation.evidence_and_explanation["model_evidence"] = {
            "shared_values": {
                "shared_actor": ["Moth Lantern"],
                "shared_malware": [],
                "shared_tool": [],
                "shared_technique": [],
                "shared_indicator": [],
            }
        }
        session.add(correlation)
        await session.commit()

        provider = FixtureCampaignNamingProvider()
        naming_service = CampaignNamingService(provider, model="fixture-campaign-model")
        discovered = await discover_campaigns(session, naming_service=naming_service)
        await session.commit()

        assert len(discovered) == 1
        campaign = discovered[0]
        assert campaign.name == "Moth Lantern Activity Cluster"
        assert campaign.evidence["classification"] == "correlation_discovered_candidate"
        assert campaign.evidence["naming"]["status"] == "ai_generated"
        assert campaign.evidence["naming"]["model"] == "fixture-campaign-model"
        assert campaign.evidence["supporting_report_ids"] == sorted(
            [str(first.id), str(second.id)]
        )
        assert "Nightfall" not in provider.requests[0].user_prompt
        assert campaign.id != synthetic.id

        saved_probability = correlation.correlation_probability
        second_discovery = await discover_campaigns(
            session,
            naming_service=naming_service,
        )
        await session.commit()

        assert len(second_discovery) == 1
        assert second_discovery[0].id == campaign.id
        assert len(provider.requests) == 1
        assert correlation.correlation_probability == saved_probability
        campaign_count = await session.scalar(
            select(func.count()).select_from(Campaign)
        )
        assert campaign_count == 2
        histories = (
            await session.execute(
                select(CampaignHistory).where(CampaignHistory.campaign_id == campaign.id)
            )
        ).scalars().all()
        assert [event.event_type for event in histories] == ["discovered"]

    await engine.dispose()


@pytest.mark.asyncio
async def test_five_report_group_discovered_with_absent_and_below_threshold_pairs() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        source = CTISource(
            name="Five Report Source",
            source_type=SourceType.RESEARCH,
            base_url="https://example.test/five-reports",
            configuration={},
        )
        session.add(source)
        await session.flush()
        docs = [_document(source.id, f"report-{i}") for i in range(1, 6)]
        for doc in docs:
            doc.original_title = f"Document {doc.canonical_key} title"
            doc.normalized_content = f"Content for {doc.canonical_key}."
        session.add_all(docs)
        await session.flush()

        r1, r2, r3, r4, r5 = docs
        # 8 strong edges out of 10 possible pairs:
        # (r1, r2), (r2, r3), (r3, r4), (r4, r5), (r5, r1), (r1, r3), (r2, r4), (r3, r5)
        # Pair (r1, r4) is completely ABSENT.
        # Pair (r2, r5) is BELOW THRESHOLD (prob 0.20 < 0.35).
        strong_pairs = [
            (r1, r2, 0.85),
            (r2, r3, 0.84),
            (r3, r4, 0.83),
            (r4, r5, 0.82),
            (r5, r1, 0.81),
            (r1, r3, 0.80),
            (r2, r4, 0.79),
            (r3, r5, 0.78),
        ]
        strong_corrs = []
        for d1, d2, prob in strong_pairs:
            c = _correlation(d1, d2, prob, available=True)
            c.evidence_and_explanation["model_evidence"] = {
                "shared_values": {
                    "shared_actor": ["Moth Lantern"],
                    "shared_malware": [],
                    "shared_tool": [],
                    "shared_technique": [],
                    "shared_indicator": [],
                }
            }
            strong_corrs.append(c)

        # Below threshold pair (r2, r5) with prob 0.20
        below_thresh = _correlation(r2, r5, 0.20, available=True)
        below_thresh.evidence_and_explanation["model_evidence"] = {
            "shared_values": {
                "shared_actor": [],
                "shared_malware": [],
                "shared_tool": [],
                "shared_technique": [],
                "shared_indicator": [],
            }
        }

        session.add_all(strong_corrs + [below_thresh])
        await session.commit()

        provider = FixtureCampaignNamingProvider()
        naming_service = CampaignNamingService(provider, model="fixture-campaign-model")
        discovered = await discover_campaigns(
            session,
            probability_threshold=0.35,
            minimum_similarity=0.1,
            naming_service=naming_service,
        )
        await session.commit()

        # Exactly 1 campaign candidate containing all 5 reports
        assert len(discovered) == 1
        campaign = discovered[0]
        assert campaign.evidence["member_count"] == 5
        assert set(campaign.evidence["supporting_report_ids"]) == {str(d.id) for d in docs}

        # Supporting correlation IDs contain ONLY the 8 qualifying edges (absent and below-threshold excluded)
        qualifying_ids = {str(c.id) for c in strong_corrs}
        assert set(campaign.evidence["supporting_correlation_ids"]) == qualifying_ids
        assert str(below_thresh.id) not in campaign.evidence["supporting_correlation_ids"]

        # Below-threshold edge is captured in contradictions in evidence
        user_prompt = provider.requests[0].user_prompt
        assert "EVIDENCE_DATA:" in user_prompt
        assert str(below_thresh.id) in user_prompt

        # The 5 reports are associated in database
        associations = (
            await session.execute(
                select(CampaignDocumentAssociation).where(
                    CampaignDocumentAssociation.campaign_id == campaign.id
                )
            )
        ).scalars().all()
        assert len(associations) == 5

    await engine.dispose()


@pytest.mark.asyncio
async def test_sparse_chain_and_weak_bridge_do_not_merge_unsupported_reports() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        source = CTISource(
            name="Sparse Chain Source",
            source_type=SourceType.RESEARCH,
            base_url="https://example.test/sparse-chain",
            configuration={},
        )
        session.add(source)
        await session.flush()

        # Part 1: 5-report sparse linear chain r1 - r2 - r3 - r4 - r5
        docs = [_document(source.id, f"chain-report-{i}") for i in range(1, 6)]
        session.add_all(docs)
        await session.flush()
        r1, r2, r3, r4, r5 = docs
        chain_corrs = [
            _correlation(r1, r2, 0.85, available=True),
            _correlation(r2, r3, 0.84, available=True),
            _correlation(r3, r4, 0.83, available=True),
            _correlation(r4, r5, 0.82, available=True),
        ]
        session.add_all(chain_corrs)
        await session.commit()

        provider = FixtureCampaignNamingProvider()
        naming_service = CampaignNamingService(provider, model="fixture-campaign-model")
        discovered = await discover_campaigns(session, naming_service=naming_service)
        await session.commit()

        # No 5-report campaign candidate is formed; endpoints r1 and r5 are never merged
        memberships = [set(c.evidence["supporting_report_ids"]) for c in discovered]
        assert not any(len(m) >= 3 for m in memberships)
        assert not any({str(r1.id), str(r5.id)}.issubset(m) for m in memberships)

    await engine.dispose()


@pytest.mark.asyncio
async def test_strong_contradictory_edge_blocks_group_merge() -> None:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async with factory() as session:
        source = CTISource(
            name="Contradiction Test Source",
            source_type=SourceType.RESEARCH,
            base_url="https://example.test/contradiction-test",
            configuration={},
        )
        session.add(source)
        await session.flush()
        docs = [_document(source.id, f"contra-report-{i}") for i in range(1, 6)]
        session.add_all(docs)
        await session.flush()
        r1, r2, r3, r4, r5 = docs

        # 8 strong edges that would otherwise form a 5-report group
        strong_pairs = [
            (r1, r2, 0.85),
            (r2, r3, 0.84),
            (r3, r4, 0.83),
            (r4, r5, 0.82),
            (r5, r1, 0.81),
            (r1, r3, 0.80),
            (r2, r4, 0.79),
            (r3, r5, 0.78),
        ]
        strong_corrs = [_correlation(d1, d2, prob, available=True) for d1, d2, prob in strong_pairs]

        # Strong contradictory edge: pair (r1, r4) is explicitly labeled "unrelated"
        contra_record = _correlation(r1, r4, 0.80, available=True)
        contra_record.predicted_relationship_label = "unrelated"

        session.add_all(strong_corrs + [contra_record])
        await session.commit()

        provider = FixtureCampaignNamingProvider()
        naming_service = CampaignNamingService(provider, model="fixture-campaign-model")
        discovered = await discover_campaigns(session, naming_service=naming_service)
        await session.commit()

        # The 5-report group MUST NOT be merged because of the contradictory edge
        memberships = [set(c.evidence["supporting_report_ids"]) for c in discovered]
        for m in memberships:
            assert not ({str(r1.id), str(r4.id)} <= m)
        assert not any(len(m) == 5 for m in memberships)

    await engine.dispose()
