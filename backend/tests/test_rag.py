from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import CTIDocument, CTISource, SourceType
from app.rag.service import HybridRetrievalService, RetrievalFilters
from app.vector_store.qdrant import SemanticSearchResult


class FakeSemanticService:
    class Index:
        collection_name = "test_documents"

    index = Index()

    def search(self, query, **filters):
        return [
            SemanticSearchResult(
                document_id=DOCUMENT_ID,
                chunk_id="chunk-1",
                score=0.91,
                text="Ransomware operations target hospitals.",
                metadata={
                    "title": "Public advisory",
                    "source_url": "https://source.test/advisory",
                    "published_at": "2026-11-16T00:00:00+00:00",
                    "source_reliability": 0.9,
                    "embedding_model": "test-v1",
                },
            )
        ]


class FakeGraphService:
    def search(self, query, limit):
        return [
            {
                "node": {
                    "stable_id": f"ThreatReport:{DOCUMENT_ID}",
                    "name": "Public advisory",
                    "source_url": "https://source.test/advisory",
                    "published_at": "2026-11-16T00:00:00+00:00",
                },
                "neighbor": {"stable_id": "Malware:example", "name": "Example Malware"},
                "relationship": {"relationship_type": "MENTIONS"},
            }
        ]


DOCUMENT_ID = uuid4()


@pytest.mark.asyncio
async def test_hybrid_retrieval_preserves_sources_filters_and_deduplicates():
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    now = datetime(2026, 11, 16, tzinfo=timezone.utc)
    async with session_factory() as session:
        source = CTISource(
            name="Public Advisory",
            source_type=SourceType.ADVISORY,
            base_url="https://source.test",
            reliability_score=0.9,
            configuration={},
        )
        session.add(source)
        await session.flush()
        session.add(
            CTIDocument(
                id=DOCUMENT_ID,
                source_id=source.id,
                canonical_key="public-advisory-1",
                title="Public advisory",
                normalized_content="Ransomware operations target hospitals.",
                normalized_text="Ransomware operations target hospitals.",
                normalized_title="Public advisory",
                original_url="https://source.test/advisory",
                document_type="advisory",
                document_status="normalized",
                retrieved_at=now,
                published_at=now,
                provenance={"source_reference": "advisory-1"},
            )
        )
        await session.commit()

        response = await HybridRetrievalService(
            FakeSemanticService(),
            FakeGraphService(),
        ).retrieve(
            session,
            "ransomware",
            filters=RetrievalFilters(document_type="advisory"),
            limit=10,
        )

    assert response.sufficient_evidence is True
    assert response.evidence
    assert response.evidence[0].source_url == "https://source.test/advisory"
    assert response.evidence[0].source_reliability == 0.9
    assert len({(item.document_id, item.relevant_text) for item in response.evidence}) == len(response.evidence)
    assert response.source_references[0]["document_id"] == str(DOCUMENT_ID)
    assert "Ransomware operations" in response.context
    await engine.dispose()


@pytest.mark.asyncio
async def test_hybrid_retrieval_reports_insufficient_evidence():
    class EmptySemantic:
        class Index:
            collection_name = "test"

        index = Index()

        def search(self, query, **filters):
            return []

    class EmptyGraph:
        def search(self, query, limit):
            return []

    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_sessionmaker(engine, expire_on_commit=False)() as session:
        response = await HybridRetrievalService(EmptySemantic(), EmptyGraph()).retrieve(
            session, "unknown threat"
        )
    assert response.sufficient_evidence is False
    assert "insufficient_evidence" in response.warnings
    await engine.dispose()
