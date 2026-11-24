from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import GeneratedReport, Investigation, InvestigationStatus
from app.reports.service import build_report_markdown, generate_report


def _investigation() -> Investigation:
    return Investigation(
        id=uuid4(),
        title="Ransomware investigation",
        status=InvestigationStatus.CLOSED,
        request_query="What happened?",
        objective="What happened?",
        findings={},
        model_output={
            "status": "completed",
            "confirmed_facts": [
                {"text": "A ransomware operation was reported.", "evidence_ids": ["semantic:1"]}
            ],
            "inferred_relationships": [],
            "recommendations": [],
        },
        evidence_references=[
            {
                "evidence_id": "semantic:1",
                "document_id": str(uuid4()),
                "document_title": "Public advisory",
                "source_url": "https://source.test/advisory",
                "evidence_type": "semantic_chunk",
            }
        ],
        provider_metadata={"provider": "baseline_heuristic", "retrieval_warnings": []},
    )


@pytest.mark.asyncio
async def test_report_generation_creates_downloadable_pdf_and_references():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        report = await generate_report(
            session,
            _investigation(),
            report_type="technical",
            report_format="pdf",
        )
        assert report.content_bytes.startswith(b"%PDF")
        assert "https://source.test/advisory" in report.content
        assert "baseline heuristic" in report.content
        await session.commit()
        stored = await session.get(GeneratedReport, report.id)
        assert stored is not None
        assert stored.content_bytes.startswith(b"%PDF")
    await engine.dispose()


def test_report_with_missing_evidence_is_explicit():
    investigation = _investigation()
    investigation.evidence_references = []
    markdown = build_report_markdown(investigation, "executive")
    assert "No grounded evidence available" in markdown
    assert "No evidence references were available" in markdown
