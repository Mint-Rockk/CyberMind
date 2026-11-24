import json

import pytest

from app.campaigns.naming import (
    CampaignNamingService,
    redact_synthetic_campaign_labels,
)
from app.genai.base import LLMResponse, LLMUnavailableError


def _evidence() -> dict:
    return {
        "report_ids": ["report-1", "report-2"],
        "source_names": ["Research Feed"],
        "correlation_ids": ["correlation-1"],
        "shared_entities": {
            "actors": ["Moth Lantern"],
            "malware": [],
            "tools": [],
            "techniques": [],
            "indicators": [],
        },
        "contradictions": [],
        "reports": [
            {
                "report_id": "report-1",
                "title": "Actor activity follow-up",
                "content_excerpt": "Technical details from a report.",
            },
            {
                "report_id": "report-2",
                "title": "Related activity",
                "content_excerpt": "A second report excerpt.",
            },
        ],
    }


def _response_content(evidence: dict, *, name: str = "Moth Lantern Activity") -> str:
    report_ids = evidence["report_ids"]
    correlation_id = evidence["correlation_ids"][0]
    return json.dumps({
        "name": name,
        "description": "A provisional cluster supported by shared reporting.",
        "activity_summary": {
            "text": "The reports describe activity associated with Moth Lantern.",
            "evidence_ids": report_ids,
        },
        "main_supporting_evidence": [
            {
                "text": "The saved pair prediction supports a relationship.",
                "evidence_ids": [correlation_id],
            }
        ],
        "grouping_rationale": {
            "text": "The reports have a direct saved strong-correlation edge.",
            "evidence_ids": [correlation_id],
        },
        "shared_entities": evidence["shared_entities"],
        "source_names": evidence["source_names"],
        "report_ids": report_ids,
        "contradictions_or_limitations": [],
        "analyst_review_required": True,
    })


class FixtureProvider:
    def __init__(self, content: str) -> None:
        self.content = content
        self.requests = []

    async def generate(self, request):
        self.requests.append(request)
        return LLMResponse(
            content=self.content,
            provider="fixture-provider",
            model="fixture-campaign-model",
            response_id="fixture-response",
            usage={"total_tokens": 123},
        )


class UnavailableProvider:
    async def generate(self, request):
        raise LLMUnavailableError("fixture provider unavailable")


def test_synthetic_label_redaction_removes_phrase_and_distinctive_terms() -> None:
    sanitized = redact_synthetic_campaign_labels(
        "Operation Nightfall report; Nightfall follow-up.",
        ["Operation Nightfall"],
    )

    assert "Operation Nightfall" not in sanitized
    assert "Nightfall" not in sanitized
    assert "withheld" in sanitized


@pytest.mark.asyncio
async def test_valid_campaign_name_records_actual_provider_and_model() -> None:
    evidence = _evidence()
    provider = FixtureProvider(_response_content(evidence))

    result = await CampaignNamingService(provider, model="fixture-campaign-model").name_campaign(
        evidence,
        synthetic_labels=["Operation Nightfall"],
    )

    assert result.name == "Moth Lantern Activity"
    assert result.metadata["status"] == "ai_generated"
    assert result.metadata["provider"] == "fixture-provider"
    assert result.metadata["model"] == "fixture-campaign-model"
    assert result.metadata["is_official_name"] is False


@pytest.mark.asyncio
async def test_invalid_or_synthetic_names_use_explicit_fallback() -> None:
    evidence = _evidence()
    provider = FixtureProvider(
        _response_content(evidence, name="Operation Nightfall")
    )

    result = await CampaignNamingService(provider).name_campaign(
        evidence,
        synthetic_labels=["Operation Nightfall"],
    )

    assert result.metadata["status"] == "fallback"
    assert result.metadata["model"] is None
    assert "Deterministic fallback" in result.description
    assert "Nightfall" not in result.name


@pytest.mark.asyncio
async def test_unsupported_entity_claim_uses_fallback() -> None:
    evidence = _evidence()
    content = json.loads(_response_content(evidence))
    content["shared_entities"]["actors"] = ["Invented Actor"]
    provider = FixtureProvider(json.dumps(content))

    result = await CampaignNamingService(provider).name_campaign(
        evidence,
        synthetic_labels=[],
    )

    assert result.metadata["status"] == "fallback"
    assert "Invented Actor" not in result.name
    assert result.metadata["fallback_reason"].startswith(
        "The provider response did not satisfy"
    )


@pytest.mark.asyncio
async def test_malformed_campaign_json_uses_fallback() -> None:
    result = await CampaignNamingService(FixtureProvider("not JSON")).name_campaign(
        _evidence(),
        synthetic_labels=[],
    )

    assert result.metadata["status"] == "fallback"
    assert result.metadata["model"] is None


@pytest.mark.asyncio
async def test_provider_failure_uses_visible_deterministic_fallback() -> None:
    result = await CampaignNamingService(UnavailableProvider()).name_campaign(
        _evidence(),
        synthetic_labels=[],
    )

    assert result.metadata["status"] == "fallback"
    assert result.metadata["fallback_reason"] == "fixture provider unavailable"
    assert result.metadata["analyst_review_required"] is True
    assert "GenAI naming was unavailable" in result.description


@pytest.mark.asyncio
async def test_markdown_fences_are_stripped_and_validated() -> None:
    evidence = _evidence()
    raw = _response_content(evidence)
    fenced = f"```json\n{raw}\n```"
    result = await CampaignNamingService(FixtureProvider(fenced), model="fixture-campaign-model").name_campaign(
        evidence,
        synthetic_labels=[],
    )

    assert result.metadata["status"] == "ai_generated"
    assert result.name == "Moth Lantern Activity"


@pytest.mark.asyncio
async def test_alias_mapping_coerces_flat_entities_and_legacy_fields() -> None:
    evidence = _evidence()
    legacy_content = json.dumps({
        "campaign_name": "Moth Lantern Phishing Activity",
        "description": "Cross-source phishing campaign targeting banking sector.",
        "reasoning": "The reports share strong correlation and overlapping Moth Lantern attribution.",
        "supporting_report_ids": evidence["report_ids"],
        "supporting_sources": evidence["source_names"],
        "shared_actors": ["Moth Lantern"],
        "shared_malware": [],
        "shared_tools": [],
        "shared_techniques": [],
        "shared_indicators": [],
        "limitations": [
            "Provisional correlation requires analyst review."
        ],
        "requires_analyst_verification": True,
    })
    result = await CampaignNamingService(FixtureProvider(legacy_content), model="fixture-campaign-model").name_campaign(
        evidence,
        synthetic_labels=[],
    )

    assert result.metadata["status"] == "ai_generated"
    assert result.name == "Moth Lantern Phishing Activity"
    assert result.metadata["shared_entities"]["actors"] == ["Moth Lantern"]


@pytest.mark.asyncio
async def test_openai_compatible_provider_retries_transient_503(monkeypatch: pytest.MonkeyPatch) -> None:
    import httpx
    from app.genai.openai_compatible import OpenAICompatibleProvider
    from app.genai.base import LLMRequest

    call_count = 0

    def mock_post(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if call_count < 2:
            return httpx.Response(503, request=request, json={"error": "High demand"})
        return httpx.Response(200, request=request, json={
            "id": "resp-1",
            "model": "test-model",
            "choices": [{"message": {"role": "assistant", "content": '{"name": "test"}'}}],
            "usage": {"total_tokens": 10},
        })

    client = httpx.AsyncClient(transport=httpx.MockTransport(mock_post))
    provider = OpenAICompatibleProvider(
        api_key="test-key",
        base_url="https://api.test/v1",
        default_model="test-model",
        timeout=10.0,
        client=client,
    )
    async def instant_sleep(_seconds: float) -> None:
        return

    monkeypatch.setattr("asyncio.sleep", instant_sleep)

    res = await provider.generate(LLMRequest(system_prompt="", user_prompt="test", model="test-model"))
    assert res.content == '{"name": "test"}'
    assert call_count == 2


