from datetime import datetime, timezone

import pytest

from app.collectors.base import CollectedRecord
from app.normalization.service import (
    find_duplicate,
    normalize_record,
    serialize_raw_content,
)


def record(**overrides) -> CollectedRecord:
    values = {
        "external_id": "advisory-1",
        "title": "  Example advisory  ",
        "content": "<html><script>drop</script><body>Threat  report\nwith details.</body></html>",
        "source_url": "https://example.test/advisory",
        "original_reference": "https://example.test/advisory",
        "collected_at": datetime(2026, 1, 2, 12, 0),
        "published_at": "2026-01-02T10:00:00-02:00",
        "payload": {},
        "content_type": "text/html",
        "metadata": {"source_type": "advisory"},
    }
    values.update(overrides)
    return CollectedRecord(**values)


def test_html_cleaning_and_utc_timestamp_conversion() -> None:
    normalized = normalize_record(record())
    assert normalized.normalized_text == "Threat report with details."
    assert normalized.normalized_title == "Example advisory"
    assert normalized.collected_at == datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
    assert normalized.published_at == datetime(2026, 1, 2, 12, tzinfo=timezone.utc)
    assert normalized.document_type == "advisory"


def test_hash_is_stable_and_exact_duplicate_is_detected() -> None:
    first = normalize_record(record())
    second = normalize_record(record(content="<p>Threat report with details.</p>"))
    assert first.content_hash == second.content_hash
    duplicate, relationship, score = find_duplicate(second, [
        type("Document", (), {
            "content_hash": first.content_hash,
            "normalized_text": first.normalized_text,
            "normalized_content": first.normalized_text,
        })()
    ])
    assert duplicate is not None
    assert relationship == "exact"
    assert score == 100


def test_near_duplicate_is_detected() -> None:
    first = normalize_record(record(content="A threat report describes a phishing campaign targeting analysts."))
    second = normalize_record(record(content="A threat report describes a phishing campaign targeting security analysts."))
    duplicate, relationship, score = find_duplicate(second, [
        type("Document", (), {
            "content_hash": first.content_hash,
            "normalized_text": first.normalized_text,
            "normalized_content": first.normalized_text,
        })()
    ])
    assert duplicate is not None
    assert relationship == "near"
    assert score is not None and score >= 92


def test_missing_metadata_and_invalid_content_are_rejected() -> None:
    structured = normalize_record(record(content="", payload={"description": "Structured advisory"}))
    assert structured.normalized_text == "Structured advisory"
    with pytest.raises(ValueError):
        normalize_record(record(title=" ", content="content"))
    with pytest.raises(ValueError):
        normalize_record(record(content="", payload={}))


def test_nul_bytes_are_removed_before_text_persistence() -> None:
    source = record(content="Threat\x00 report")
    normalized = normalize_record(source)
    assert "\x00" not in normalized.normalized_text
    assert "\x00" not in serialize_raw_content(source)
