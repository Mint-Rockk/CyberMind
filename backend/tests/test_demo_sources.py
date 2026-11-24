from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import CTIDocument, CTISource, SourceType
from app.demo.data import REPORTS, SITES, demo_report_counts, feed_payload, reports_for_site
from app.extraction.service import extract_entities
from app.demo.seed import seed_demo_sources
from app.main import app


def test_demo_corpus_has_five_sites_and_forty_reports() -> None:
    assert len(SITES) == 5
    assert len(REPORTS) == 40
    assert [len(reports_for_site(site["slug"])) for site in SITES] == [8] * 5
    counts = demo_report_counts()
    assert counts["partial_evidence"] >= 5
    assert counts["hard_negative"] >= 5
    assert counts["unrelated"] >= 8
    assert sum(bool(report["campaign_name"]) for report in REPORTS) >= 20
    assert len({report["duplicate_scenario"] for report in REPORTS if report["duplicate_scenario"]}) >= 3


def test_demo_feed_contains_stable_article_urls_and_fictional_labels() -> None:
    feed = feed_payload("cyberwatch")
    assert feed["fictional_demo"] is True
    assert len(feed["items"]) == 8
    assert all(item["fictional_demo"] is True for item in feed["items"])
    assert all(item["url"].startswith("http://127.0.0.1:8000/demo-sites/") for item in feed["items"])


def test_demo_report_text_supports_core_entity_extraction() -> None:
    types = {
        mention.entity_type.value
        for report in REPORTS
        for mention in extract_entities(report["content"], report)
    }
    assert {"threat_actor", "malware", "tool", "cve", "ip_address", "domain", "url", "file_hash", "sector", "attack_reference"} <= types


def test_demo_sites_are_mounted_at_local_root_not_api_prefix() -> None:
    paths = app.openapi()["paths"]
    assert "/demo-sites/{slug}/feed.json" in paths
    assert "/api/v1/demo-sites/{slug}/feed.json" not in paths


@pytest.mark.asyncio
async def test_source_seed_is_idempotent_and_preserves_old_documents() -> None:
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        external = CTISource(
            name="Old Public Feed",
            source_type=SourceType.RSS,
            base_url="https://source.example/feed.xml",
            is_active=True,
            configuration={},
        )
        session.add(external)
        await session.flush()
        old_document = CTIDocument(
            source_id=external.id,
            canonical_key="historical-document",
            title="Historical report",
            normalized_content="Historical content",
            normalized_text="Historical content",
            retrieved_at=datetime.now(timezone.utc),
            document_status="normalized",
            provenance={},
        )
        session.add(old_document)
        await session.commit()

    assert await seed_demo_sources(factory) == 5
    assert await seed_demo_sources(factory) == 5
    async with factory() as session:
        sources = list((await session.execute(select(CTISource))).scalars().all())
        assert len(sources) == 6
        assert sum(source.is_active for source in sources) == 5
        assert len([source for source in sources if (source.configuration or {}).get("local_demo_feed")]) == 5
        historical = await session.get(CTIDocument, old_document.id)
        assert historical is not None
        assert not next(source for source in sources if source.name == "Old Public Feed").is_active
    await engine.dispose()

