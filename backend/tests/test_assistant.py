from uuid import uuid4
from types import SimpleNamespace

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.db.models import AssistantConversation
from app.genai.assistant import send_assistant_message
from app.genai.base import LLMResponse, LLMUnavailableError
from app.rag.service import EvidenceItem, RetrievalResponse


EVIDENCE_ID = "semantic:chunk-1"


class FakeRetrieval:
    def __init__(self, evidence: list[EvidenceItem]):
        self.evidence = evidence

    async def retrieve(self, session, query, *, filters, limit):
        return RetrievalResponse(
            query=query,
            evidence=self.evidence,
            source_references=[
                {"evidence_id": item.evidence_id, "title": item.document_title}
                for item in self.evidence
            ],
            context="\n".join(item.relevant_text for item in self.evidence),
            sufficient_evidence=bool(self.evidence),
        )


class FakeProvider:
    async def generate(self, request):
        return LLMResponse(
            content=(
                '{"status":"completed","confirmed_facts":['
                '{"text":"A ransomware operation was reported.",'
                f'"evidence_ids":["{EVIDENCE_ID}"]}}],'
                '"inferred_relationships":[],"model_interpretations":[],'
                '"recommendations":[],"intelligence_gaps":[],"timeline":[]}'
            ),
            provider="test",
            model="test-model",
            response_id=None,
            usage={},
        )


@pytest.mark.asyncio
async def test_assistant_returns_grounded_answer_and_context(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    evidence = [
        EvidenceItem(
            evidence_id=EVIDENCE_ID,
            evidence_type="semantic_chunk",
            score=0.9,
            document_id=uuid4(),
            document_title="Public advisory",
            source_url="https://source.test/advisory",
            chunk_id="chunk-1",
            relevant_text="A ransomware operation was reported.",
            publication_timestamp=None,
            source_reliability=0.9,
            provenance={"retriever": "test"},
        )
    ]
    monkeypatch.setattr("app.genai.assistant.create_provider", lambda: FakeProvider())
    async with session_factory() as session:
        conversation = AssistantConversation(title="Test")
        session.add(conversation)
        await session.flush()
        response = await send_assistant_message(
            session,
            FakeRetrieval(evidence),
            conversation,
            content="What happened?",
        )
        assert response.model_output["confirmed_facts"][0]["evidence_ids"] == [EVIDENCE_ID]
        assert response.evidence_references[0]["evidence_id"] == EVIDENCE_ID
    await engine.dispose()


@pytest.mark.asyncio
async def test_assistant_marks_unanswerable_questions(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(
        "app.genai.assistant.create_provider",
        lambda: pytest.fail("Provider must not be called without evidence"),
    )
    async with session_factory() as session:
        conversation = AssistantConversation(title="Test")
        session.add(conversation)
        await session.flush()
        response = await send_assistant_message(
            session,
            FakeRetrieval([]),
            conversation,
            content="What is not in the collected intelligence?",
        )
        assert response.model_output["status"] == "insufficient_evidence"
        assert response.model_output["confirmed_facts"] == []
        assert response.provider_metadata["provider"] == "not_called"
    await engine.dispose()


@pytest.mark.asyncio
async def test_assistant_returns_cited_excerpts_when_genai_is_disabled(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite://")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    evidence = [
        EvidenceItem(
            evidence_id=EVIDENCE_ID,
            evidence_type="semantic_chunk",
            score=0.9,
            document_id=uuid4(),
            document_title="Nightfall bulletin",
            source_url="http://127.0.0.1:8000/demo-sites/cyberwatch/reports/CW-NF-01",
            chunk_id="chunk-1",
            relevant_text="The fictional NightJar family appeared in the Operation Nightfall exercise.",
            publication_timestamp=None,
            source_reliability=0.8,
            provenance={"retriever": "test"},
        )
    ]
    monkeypatch.setattr(
        "app.genai.assistant.create_provider",
        lambda: (_ for _ in ()).throw(LLMUnavailableError("GenAI provider is disabled")),
    )
    monkeypatch.setattr(
        "app.genai.assistant.get_settings",
        lambda: SimpleNamespace(genai_provider="disabled"),
    )
    async with session_factory() as session:
        conversation = AssistantConversation(title="Offline test")
        session.add(conversation)
        await session.flush()
        response = await send_assistant_message(
            session,
            FakeRetrieval(evidence),
            conversation,
            content="What is Operation Nightfall?",
        )
        assert response.provider_metadata["provider"] == "offline_extractive"
        assert response.model_output["status"] == "grounded_extractive"
        assert response.model_output["confirmed_facts"][0]["evidence_ids"] == [EVIDENCE_ID]
        assert response.evidence_references[0]["evidence_id"] == EVIDENCE_ID
    await engine.dispose()
