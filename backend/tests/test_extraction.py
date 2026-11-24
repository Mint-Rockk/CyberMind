from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import (
    CTIDocument,
    CTISource,
    DocumentEntityAssociation,
    ExtractedEntity,
    SourceType,
)
from app.db.models import EntityType
from app.extraction.service import extract_entities, persist_document_entities


def test_extracts_indicators_and_references_with_evidence_spans() -> None:
    text = (
        "APT28 used Cobalt Strike against healthcare organizations. "
        "The report links CVE-2024-12345 to T1059.001 and hosts at "
        "https://evil.example/path and 203.0.113.10. "
        "The sample hash is 0123456789abcdef0123456789abcdef."
    )
    mentions = extract_entities(text)
    by_type = {(mention.entity_type, mention.normalized_name): mention for mention in mentions}

    assert (EntityType.THREAT_ACTOR, "APT28") in by_type
    assert (EntityType.TOOL, "Cobalt Strike") in by_type
    assert (EntityType.SECTOR, "Healthcare") in by_type
    assert (EntityType.CVE, "CVE-2024-12345") in by_type
    assert (EntityType.ATTACK_REFERENCE, "T1059.001") in by_type
    assert (EntityType.URL, "https://evil.example/path") in by_type
    assert (EntityType.DOMAIN, "evil.example") in by_type
    assert (EntityType.IP_ADDRESS, "203.0.113.10") in by_type
    assert (EntityType.FILE_HASH, "0123456789abcdef0123456789abcdef") in by_type
    actor = by_type[(EntityType.THREAT_ACTOR, "APT28")]
    assert text[actor.start:actor.end] == actor.original_text
    assert actor.evidence_text.startswith("APT28 used")


def test_extracts_campaign_vulnerability_ransomware_and_aliases() -> None:
    text = (
        "Fancy Bear launched Operation NightDragon using LockBit 3.0. "
        "The zero-day enabled remote code execution."
    )
    mentions = extract_entities(text)
    values = {(mention.entity_type, mention.normalized_name) for mention in mentions}
    assert (EntityType.THREAT_ACTOR, "APT28") in values
    assert (EntityType.RANSOMWARE, "LockBit 3.0") in values
    assert (EntityType.CAMPAIGN, "nightdragon") in values
    assert (EntityType.VULNERABILITY, "zero-day") in values
    assert (EntityType.VULNERABILITY, "remote code execution") in values


def test_structured_metadata_is_supported_without_merging_types() -> None:
    mentions = extract_entities(
        "The advisory contains no named actor.",
        {
            "malware": ["ExampleDropper"],
            "campaign": ["Spring Test"],
            "attack_reference": ["T1566"],
        },
    )
    values = {(mention.entity_type, mention.normalized_name) for mention in mentions}
    assert (EntityType.MALWARE, "exampledropper") in values
    assert (EntityType.CAMPAIGN, "spring test") in values
    assert (EntityType.ATTACK_REFERENCE, "T1566") in values
    assert all(mention.extraction_method == "structured_metadata" for mention in mentions)


@pytest.mark.asyncio
async def test_persistence_deduplicates_entities_and_keeps_document_evidence() -> None:
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
            name="Extraction Fixture Source",
            source_type=SourceType.ADVISORY,
            base_url="https://example.test",
            configuration={},
        )
        session.add(source)
        await session.flush()
        document = CTIDocument(
            source_id=source.id,
            canonical_key="extraction-fixture",
            title="Entity fixture",
            normalized_content="APT28 used 203.0.113.10.",
            normalized_text="APT28 used 203.0.113.10.",
            original_title="Entity fixture",
            normalized_title="Entity fixture",
            original_url="https://example.test/entity",
            content_hash="entity-fixture",
            document_type="advisory",
            document_status="normalized",
            retrieved_at=datetime.now(timezone.utc),
            provenance={},
        )
        session.add(document)
        await session.flush()
        mentions = await persist_document_entities(session, document)
        await session.commit()
        assert len(mentions) == 3
        entities = (await session.execute(select(ExtractedEntity))).scalars().all()
        associations = (
            await session.execute(select(DocumentEntityAssociation))
        ).scalars().all()
        assert len(entities) == 3
        assert len(associations) == 3
        assert all(association.evidence_text for association in associations)
    await engine.dispose()
