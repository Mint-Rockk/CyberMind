import httpx
import pytest

from app.genai.base import LLMRequest, LLMUnavailableError
from app.genai.investigation import _validate_evidence_ids
from app.genai.openai_compatible import OpenAICompatibleProvider
from app.genai.prompting import SYSTEM_PROMPT, build_investigation_prompt
from app.genai.schemas import GroundedStatement, InvestigationOutput


def test_provider_requires_api_key():
    with pytest.raises(LLMUnavailableError, match="GENAI_API_KEY"):
        OpenAICompatibleProvider(
            api_key=None,
            base_url="https://example.test/v1",
            default_model="test",
            timeout=1,
        )


@pytest.mark.asyncio
async def test_provider_rejects_malformed_response():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": []})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        default_model="test",
        timeout=1,
        client=client,
    )
    with pytest.raises(LLMUnavailableError, match="empty content"):
        await provider.generate(LLMRequest("system", "user", "test"))
    await client.aclose()


@pytest.mark.asyncio
async def test_provider_surfaces_http_failure():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, json={"error": "upstream unavailable"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://example.test/v1",
        default_model="test",
        timeout=1,
        client=client,
    )
    with pytest.raises(LLMUnavailableError, match="HTTP 502"):
        await provider.generate(LLMRequest("system", "user", "test"))
    await client.aclose()


def test_grounding_rejects_unknown_evidence():
    output = InvestigationOutput(
        status="completed",
        confirmed_facts=[GroundedStatement(text="fact", evidence_ids=["semantic:missing"])],
    )
    with pytest.raises(ValueError, match="evidence ID"):
        _validate_evidence_ids(output, {"semantic:known"})


def test_system_prompt_and_context_treat_cti_as_untrusted_data():
    class Retrieval:
        evidence = []
        warnings = []

    assert "untrusted data" in SYSTEM_PROMPT
    prompt = build_investigation_prompt("query", Retrieval())
    assert "EVIDENCE_DATA" in prompt
