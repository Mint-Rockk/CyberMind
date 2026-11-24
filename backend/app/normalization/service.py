import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from bs4 import BeautifulSoup
from dateutil import parser as date_parser
from rapidfuzz import fuzz

from app.collectors.base import CollectedRecord
from app.db.models import CTIDocument, NormalizationStatus

NEAR_DUPLICATE_THRESHOLD = 92
_WHITESPACE = re.compile(r"\s+")
_NUL = "\x00"


@dataclass(frozen=True)
class NormalizedDocument:
    original_title: str
    normalized_title: str
    normalized_text: str
    content_hash: str
    original_url: str
    published_at: datetime | None
    collected_at: datetime
    document_type: str
    language: str | None
    provenance: dict[str, Any]


def _utc_datetime(value: datetime | str | None) -> datetime | None:
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else date_parser.parse(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _clean_text(value: str) -> str:
    value = value.replace(_NUL, "")
    soup = BeautifulSoup(value, "html.parser")
    for element in soup(["script", "style", "noscript", "template"]):
        element.decompose()
    return _WHITESPACE.sub(" ", soup.get_text(" ", strip=True)).strip()


def _structured_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return " ".join(_structured_text(item) for item in value.values())
    if isinstance(value, list):
        return " ".join(_structured_text(item) for item in value)
    return str(value) if value is not None else ""


def _document_type(record: CollectedRecord) -> str:
    explicit = record.metadata.get("document_type") or record.payload.get("document_type")
    if explicit:
        return str(explicit).lower().replace(" ", "_")[:64]
    content_type = (record.content_type or "").lower()
    if "stix" in content_type or record.payload.get("type"):
        return "stix"
    if "html" in content_type:
        return "advisory"
    source_type = record.metadata.get("source_type")
    return str(source_type or "unknown").lower().replace(" ", "_")[:64]


def normalize_record(record: CollectedRecord) -> NormalizedDocument:
    if not record.external_id.strip() or not record.source_url.strip():
        raise ValueError("A source record requires an external_id and source_url")
    original_title = record.title.strip()
    if not original_title:
        raise ValueError("A source record requires a title")
    raw_text = record.content or _structured_text(record.payload)
    normalized_text = _clean_text(raw_text)
    if not normalized_text:
        raise ValueError("A source record requires non-empty content")
    normalized_title = _WHITESPACE.sub(" ", _clean_text(original_title)).strip()
    collected_at = _utc_datetime(record.collected_at)
    if collected_at is None:
        raise ValueError("A source record requires a collection timestamp")
    content_hash = hashlib.sha256(normalized_text.casefold().encode("utf-8")).hexdigest()
    return NormalizedDocument(
        original_title=original_title,
        normalized_title=normalized_title,
        normalized_text=normalized_text,
        content_hash=content_hash,
        original_url=record.source_url,
        published_at=_utc_datetime(record.published_at),
        collected_at=collected_at,
        document_type=_document_type(record),
        language=record.metadata.get("language"),
        provenance={
            "source_url": record.source_url,
            "original_reference": record.original_reference,
            "collection_timestamp": collected_at.isoformat(),
            "normalization": "html_cleaned_and_whitespace_standardized",
        },
    )


def find_duplicate(
    normalized: NormalizedDocument,
    candidates: list[CTIDocument],
) -> tuple[CTIDocument | None, str | None, float | None]:
    for candidate in candidates:
        if candidate.content_hash == normalized.content_hash:
            return candidate, "exact", 100.0
    if not normalized.normalized_text:
        return None, None, None
    for candidate in candidates:
        candidate_text = candidate.normalized_text or candidate.normalized_content
        if candidate_text and fuzz.ratio(normalized.normalized_text, candidate_text) >= NEAR_DUPLICATE_THRESHOLD:
            score = float(fuzz.ratio(normalized.normalized_text, candidate_text))
            return candidate, "near", score
    return None, None, None


def serialize_raw_content(record: CollectedRecord) -> str:
    if record.content:
        return record.content.replace(_NUL, "")
    return json.dumps(record.payload, sort_keys=True, default=str).replace(_NUL, "")


__all__ = [
    "NEAR_DUPLICATE_THRESHOLD",
    "NormalizedDocument",
    "find_duplicate",
    "normalize_record",
    "serialize_raw_content",
]
