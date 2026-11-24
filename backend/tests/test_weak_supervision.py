from training.correlation.llm_weak_supervision import (
    WeakSupervisionLLMOutput,
    _validate_grounding,
)
from training.correlation.weak_supervision import classify_pair, extract_evidence


def _report(text: str, *, entities: list[dict] | None = None, source: str | None = None) -> dict:
    return {
        "report_id": "report",
        "normalized_text": text,
        "title": "test report",
        "source_vendor": "test",
        "source_url": source,
        "referenced_urls": [],
        "published_at": "2024-01-01T00:00:00+00:00",
        "entities": entities or [],
    }


def test_generic_overlap_is_not_a_campaign_label():
    first = extract_evidence(_report("This ransomware operation used PowerShell."))
    second = extract_evidence(_report("A different ransomware operation used PowerShell."))
    result = classify_pair(first, second)
    assert result["proposed_label"] == "uncertain"
    assert "P1" not in result["matched_rules"]


def test_same_named_operation_is_positive_with_exact_excerpts():
    first = extract_evidence(_report(
        "Operation BlueMoon targeted a public sector victim.",
        source="https://one.test/report",
    ))
    second = extract_evidence(_report(
        "The BlueMoon campaign affected a public sector victim.",
        source="https://two.test/report",
    ))
    result = classify_pair(first, second)
    assert result["proposed_label"] == "positive"
    assert "P1" in result["matched_rules"]
    assert "BlueMoon" in result["campaign_reference"]
    assert result["evidence_from_report_a"][0]["excerpt"] != result["evidence_from_report_b"][0]["excerpt"]


def test_same_actor_only_is_uncertain():
    entities = [{"type": "threat_actor", "normalized_name": "APT28"}]
    first = extract_evidence(_report(
        "Technical intrusion details describe a separate intrusion with no named operation, campaign, or incident. "
        "The report provides context but does not establish a relationship.",
        entities=entities,
    ))
    second = extract_evidence(_report(
        "Separate activity details describe another intrusion with no named operation, campaign, or incident. "
        "The report provides context but does not establish a relationship.",
        entities=entities,
    ))
    result = classify_pair(first, second)
    assert result["proposed_label"] == "uncertain"
    assert "U1" in result["matched_rules"]


def test_conflicting_rules_remain_uncertain():
    first = extract_evidence(_report("Operation BlueMoon used CVE-2024-1111 and 11111111111111111111111111111111."))
    second = extract_evidence(_report("Operation RedSun used CVE-2024-1111 and 11111111111111111111111111111111."))
    result = classify_pair(first, second)
    assert result["proposed_label"] == "uncertain"
    assert result["confidence_category"] == "low"


def test_llm_evidence_must_be_grounded_in_supplied_text_and_urls():
    output = WeakSupervisionLLMOutput(
        proposed_label="positive",
        confidence=0.8,
        evidence_from_report_a=["Operation BlueMoon"],
        evidence_from_report_b=["BlueMoon campaign"],
        shared_campaign_reference="BlueMoon",
        reasoning="Both reports explicitly name the operation.",
        source_references=["https://one.test/report"],
    )
    _validate_grounding(
        output,
        text_a="Operation BlueMoon targeted a victim.",
        text_b="The BlueMoon campaign affected a victim.",
        source_references={"https://one.test/report"},
    )
