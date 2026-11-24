from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.classification.service import classify_text
from app.classification.service import prioritize_document
from app.db.base import Base
from app.db.models import CTIDocument, CTISource, ClassificationCategory, SourceType


def test_classification_is_explainable_and_category_specific() -> None:
    result = classify_text(
        "LockBit ransomware encrypted files and used double extortion against a hospital."
    )
    assert result.category == ClassificationCategory.RANSOMWARE
    assert result.confidence >= 0.7
    assert "ransomware" in result.evidence["supporting_keywords"]
    assert "double extortion" in result.evidence["supporting_keywords"]
    assert result.method == "rule_based_v1"


def test_classification_supports_all_requested_rule_families() -> None:
    examples = {
        ClassificationCategory.PHISHING: "spearphishing email with a fake login page",
        ClassificationCategory.MALWARE: "a trojan loader delivered a malicious payload",
        ClassificationCategory.VULNERABILITY_EXPLOITATION: "CVE-2025-0001 remote code execution exploit",
        ClassificationCategory.DATA_BREACH: "data breach exposed stolen data",
        ClassificationCategory.CREDENTIAL_THEFT: "infostealer performed credential theft",
        ClassificationCategory.APT_ACTIVITY: "APT29 is a state-sponsored advanced persistent threat",
        ClassificationCategory.BOTNET: "Mirai botnet command and control",
        ClassificationCategory.SUPPLY_CHAIN_ATTACK: "dependency confusion compromised a vendor",
    }
    for expected, text in examples.items():
        assert classify_text(text).category == expected


def test_unknown_content_is_other_with_no_fake_evidence() -> None:
    result = classify_text("A general security newsletter with no threat indicators.")
    assert result.category == ClassificationCategory.OTHER
    assert result.evidence["supporting_keywords"] == []
    assert result.confidence < 0.5


@pytest.mark.asyncio
async def test_prioritization_exposes_separate_weighted_factors() -> None:
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
            name="Reliable Classification Source",
            source_type=SourceType.ADVISORY,
            base_url="https://example.test/reliable",
            reliability_score=0.9,
            configuration={},
        )
        corroborating_source = CTISource(
            name="Corroborating Classification Source",
            source_type=SourceType.RSS,
            base_url="https://example.test/corroborating",
            reliability_score=0.8,
            configuration={},
        )
        session.add_all([source, corroborating_source])
        await session.flush()
        document = CTIDocument(
            source_id=source.id,
            canonical_key="priority-one",
            title="Ransomware alert",
            normalized_title="Ransomware alert",
            normalized_content="A ransomware group encrypted files.",
            normalized_text="A ransomware group encrypted files.",
            original_url="https://example.test/one",
            content_hash="shared-priority-hash",
            document_type="advisory",
            document_status="normalized",
            retrieved_at=datetime.now(timezone.utc),
            provenance={},
        )
        corroborating_document = CTIDocument(
            source_id=corroborating_source.id,
            canonical_key="priority-two",
            title="Corroboration",
            normalized_content="A ransomware group encrypted files.",
            normalized_text="A ransomware group encrypted files.",
            original_url="https://example.test/two",
            content_hash="shared-priority-hash",
            document_type="advisory",
            document_status="normalized",
            retrieved_at=datetime.now(timezone.utc),
            provenance={},
        )
        session.add_all([document, corroborating_document])
        await session.flush()
        factors = await prioritize_document(session, document)
        assert factors["source_reliability"] == 0.9
        assert factors["information_confidence"] == 0.5
        assert factors["independent_corroboration"] == 0.5
        assert document.priority_score is not None
        assert document.priority_method == "weighted_factors_v1"
    await engine.dispose()
