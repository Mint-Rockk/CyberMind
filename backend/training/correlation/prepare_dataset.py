"""Prepare CTI-EACL24 for evidence-backed correlation-model labelling.

This module intentionally does not train a model.  CTI-EACL24 provides vendor
reports and actor/group organization, but no verified campaign-level pair
labels.  Candidate pairs are therefore emitted as ``uncertain`` review items
and never treated as supervised examples.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import warnings
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path
from typing import Iterable

from dateutil import parser as date_parser
from bs4 import XMLParsedAsHTMLWarning

from app.correlation.service import calculate_features
from app.correlation.feature_schema import FEATURE_NAMES as CANONICAL_FEATURE_NAMES
from app.correlation.types import DocumentRepresentation
from app.db.models import EntityType
from app.extraction.service import ExtractedMention, extract_entities
from app.normalization.service import _clean_text

DATASET_NAME = "CTI-EACL24"
DATASET_VERSION = "as-of-2022-06"
LABELS = {"positive", "negative", "uncertain"}
REPORT_EXTENSIONS = {".txt", ""}
DATE_IN_NAME = re.compile(r"(?<!\d)(20\d{2})[-_](\d{2})[-_](\d{2})(?!\d)")
URL_RE = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)

FEATURE_COLUMNS = (
    "temporal_similarity",
    "entity_relationship_similarity",
    "behavioural_similarity",
    "attack_technique_similarity",
    "semantic_similarity",
    "knowledge_graph_similarity",
)
CANONICAL_BY_OUTPUT_NAME = dict(zip(
    FEATURE_COLUMNS,
    CANONICAL_FEATURE_NAMES,
    strict=True,
))

warnings.filterwarnings("ignore", category=XMLParsedAsHTMLWarning)


@dataclass(frozen=True)
class SourceMetadata:
    title: str
    published_at: datetime | None
    author: str | None
    tags: tuple[str, ...]
    source_url: str | None
    vendor: str
    actor_group: str | None
    metadata_file: str | None


@dataclass
class PreparedReport:
    report_id: str
    original_filename: str
    relative_path: str
    original_text: str
    normalized_text: str
    title: str
    published_at: datetime | None
    source_vendor: str
    source_url: str | None
    actor_group: str | None
    author: str | None
    tags: tuple[str, ...]
    encoding: str
    content_hash: str
    entities: list[ExtractedMention]
    attack_techniques: tuple[str, ...]
    referenced_urls: tuple[str, ...]
    duplicate_of: str | None = None


def parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = date_parser.parse(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def decode_report(raw: bytes) -> tuple[str, str]:
    """Decode without replacing bytes silently; return text and encoding used."""
    for encoding in ("utf-8", "utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise UnicodeDecodeError("unknown", raw, 0, len(raw), "unable to decode report")


def stable_report_id(relative_path: str, content_hash: str) -> str:
    return "cti-eacl24-" + hashlib.sha256(
        f"{relative_path}\0{content_hash}".encode("utf-8")
    ).hexdigest()[:24]


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _parse_vendor_csv(csv_path: Path, dataset_root: Path) -> dict[str, SourceMetadata]:
    vendor = csv_path.parent.name
    result: dict[str, SourceMetadata] = {}
    with csv_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
        for row_number, row in enumerate(csv.reader(handle), start=1):
            if not row:
                continue
            row += [""] * (6 - len(row))
            title, date_value, author, tags, source_url, filename = (
                value.strip() for value in row[:6]
            )
            if not filename:
                continue
            candidate_path = csv_path.parent / "data" / filename
            if not candidate_path.is_file() and (candidate_path.with_suffix(".txt")).is_file():
                candidate_path = candidate_path.with_suffix(".txt")
            relative = _relative(dataset_root, candidate_path)
            result[relative] = SourceMetadata(
                title=title or Path(filename).stem,
                published_at=parse_date(date_value),
                author=author or None,
                tags=tuple(tag.strip() for tag in tags.split("|") if tag.strip()),
                source_url=source_url or None,
                vendor=vendor,
                actor_group=None,
                metadata_file=_relative(dataset_root, csv_path),
            )
    return result


def discover_report_files(dataset_root: Path) -> tuple[dict[str, SourceMetadata], list[Path]]:
    """Discover report files while excluding documentation and URL-index files."""
    metadata: dict[str, SourceMetadata] = {}
    files: list[Path] = []
    large_root = dataset_root / "threat-reports-large"
    for csv_path in sorted(large_root.glob("*/data_list.csv")):
        metadata.update(_parse_vendor_csv(csv_path, dataset_root))
    for relative in sorted(metadata):
        path = dataset_root / relative
        if path.is_file():
            files.append(path)

    grouped_root = dataset_root / "threat-reports-per-group" / "extra"
    for path in sorted(grouped_root.glob("*/*/*")):
        if not path.is_file() or path.suffix.lower() not in REPORT_EXTENSIONS:
            continue
        relative = _relative(dataset_root, path)
        group_parts = path.relative_to(grouped_root).parts
        source_kind, actor_group = group_parts[0], group_parts[1]
        date_match = DATE_IN_NAME.search(path.name)
        metadata[relative] = SourceMetadata(
            title=path.stem.replace("_", " "),
            published_at=parse_date("-".join(date_match.groups())) if date_match else None,
            author=None,
            tags=(),
            source_url=None,
            vendor=source_kind,
            actor_group=actor_group,
            metadata_file=None,
        )
        files.append(path)
    return metadata, sorted(files, key=lambda item: _relative(dataset_root, item))


def _entity_json(mention: ExtractedMention) -> dict[str, object]:
    return {
        "type": mention.entity_type.value,
        "normalized_name": mention.normalized_name,
        "original_text": mention.original_text,
        "confidence": mention.confidence,
        "evidence_text": mention.evidence_text,
        "start": mention.start,
        "end": mention.end,
        "extraction_method": mention.extraction_method,
        "extracted_at": mention.extracted_at.isoformat(),
    }


def prepare_reports(dataset_root: Path) -> tuple[list[PreparedReport], dict[str, object]]:
    metadata, files = discover_report_files(dataset_root)
    reports: list[PreparedReport] = []
    by_hash: dict[str, PreparedReport] = {}
    excluded = Counter()
    duplicate_count = 0
    for path in files:
        relative = _relative(dataset_root, path)
        try:
            raw = path.read_bytes()
            if not raw.strip():
                excluded["empty"] += 1
                continue
            original_text, encoding = decode_report(raw)
            normalized_text = _clean_text(original_text)
            if not normalized_text:
                excluded["empty_after_normalization"] += 1
                continue
        except (OSError, UnicodeError):
            excluded["unreadable_or_corrupt"] += 1
            continue
        source = metadata[relative]
        content_hash = hashlib.sha256(normalized_text.casefold().encode("utf-8")).hexdigest()
        existing = by_hash.get(content_hash)
        if existing is not None:
            duplicate_count += 1
            excluded["exact_duplicate"] += 1
            continue
        report_id = stable_report_id(relative, content_hash)
        structured = {
            "actor_group": source.actor_group,
            "source_vendor": source.vendor,
            "tags": list(source.tags),
        }
        mentions = extract_entities(normalized_text, structured)
        techniques = tuple(sorted({
            mention.normalized_name
            for mention in mentions
            if mention.entity_type == EntityType.ATTACK_REFERENCE
        }))
        report = PreparedReport(
            report_id=report_id,
            original_filename=path.name,
            relative_path=relative,
            original_text=original_text,
            normalized_text=normalized_text,
            title=source.title,
            published_at=source.published_at,
            source_vendor=source.vendor,
            source_url=source.source_url,
            actor_group=source.actor_group,
            author=source.author,
            tags=source.tags,
            encoding=encoding,
            content_hash=content_hash,
            entities=mentions,
            attack_techniques=techniques,
            referenced_urls=tuple(sorted(set(URL_RE.findall(normalized_text)))),
        )
        by_hash[content_hash] = report
        reports.append(report)
    inventory = {
        "dataset_name": DATASET_NAME,
        "dataset_version": DATASET_VERSION,
        "source_root": str(dataset_root),
        "original_report_files_discovered": len(files),
        "successfully_parsed_unique_reports": len(reports),
        "excluded_reports": dict(sorted(excluded.items())),
        "exact_duplicates": duplicate_count,
        "vendor_report_counts": dict(sorted(Counter(report.source_vendor for report in reports).items())),
        "license_notice": (
            "The repository README states that copyrights belong to the original authors "
            "or vendors, requests citation of the EACL 2024 paper, and prohibits misuse. "
            "No permissive dataset license was identified in the inspected files."
        ),
    }
    return reports, inventory


def _representation(report: PreparedReport) -> DocumentRepresentation:
    return DocumentRepresentation(
        published_at=report.published_at,
        entities=tuple(sorted({
            mention.normalized_name for mention in report.entities
        })),
        attack_techniques=report.attack_techniques,
        metadata={"report_id": report.report_id},
    )


def _candidate_keys(report: PreparedReport) -> set[str]:
    allowed = {
        EntityType.CVE,
        EntityType.FILE_HASH,
        EntityType.DOMAIN,
        EntityType.URL,
        EntityType.MALWARE,
        EntityType.RANSOMWARE,
        EntityType.TOOL,
        EntityType.CAMPAIGN,
        EntityType.ATTACK_REFERENCE,
    }
    keys = {
        f"{mention.entity_type.value}:{mention.normalized_name}"
        for mention in report.entities
        if mention.entity_type in allowed and len(mention.normalized_name) >= 4
    }
    keys.update(f"attack_reference:{value}" for value in report.attack_techniques)
    return keys


def build_uncertain_pairs(
    reports: list[PreparedReport],
) -> list[dict[str, object]]:
    blocks: defaultdict[str, set[str]] = defaultdict(set)
    by_id = {report.report_id: report for report in reports}
    for report in reports:
        for key in _candidate_keys(report):
            blocks[key].add(report.report_id)
    pairs: dict[tuple[str, str], set[str]] = defaultdict(set)
    for key, report_ids in blocks.items():
        for first, second in combinations(sorted(report_ids), 2):
            pairs[(first, second)].add(key)

    result: list[dict[str, object]] = []
    for (first_id, second_id), shared_keys in sorted(pairs.items()):
        first, second = by_id[first_id], by_id[second_id]
        vector = calculate_features(_representation(first), _representation(second))
        values = dict(zip(FEATURE_COLUMNS, vector.values, strict=True))
        evidence = (
            "Uncertain: reports share extracted CTI evidence "
            f"({', '.join(sorted(shared_keys))}), but CTI-EACL24 does not provide "
            "verified campaign-level pair labels. Human review is required."
        )
        result.append({
            "report_a_id": first_id,
            "report_b_id": second_id,
            **values,
            "label": "uncertain",
            "campaign_or_incident_group": "",
            "label_evidence": evidence,
            "feature_schema_version": "correlation-features-v1",
            "_feature_evidence": vector.evidence,
        })
    return result


def _write_csv(path: Path, fieldnames: Iterable[str], rows: Iterable[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_outputs(
    output_root: Path,
    reports: list[PreparedReport],
    inventory: dict[str, object],
    pairs: list[dict[str, object]],
) -> dict[str, object]:
    output_root.mkdir(parents=True, exist_ok=True)
    normalized_path = output_root / "normalized_reports.jsonl"
    with normalized_path.open("w", encoding="utf-8", newline="\n") as handle:
        for report in reports:
            handle.write(json.dumps({
                "report_id": report.report_id,
                "original_filename": report.original_filename,
                "relative_path": report.relative_path,
                "original_text": report.original_text,
                "normalized_text": report.normalized_text,
                "title": report.title,
                "published_at": report.published_at.isoformat() if report.published_at else None,
                "source_vendor": report.source_vendor,
                "source_url": report.source_url,
                "actor_group": report.actor_group,
                "author": report.author,
                "tags": list(report.tags),
                "encoding": report.encoding,
                "content_hash": report.content_hash,
                "entities": [_entity_json(entity) for entity in report.entities],
                "attack_techniques": list(report.attack_techniques),
                "referenced_urls": list(report.referenced_urls),
                "provenance": {
                    "dataset": DATASET_NAME,
                    "original_filename": report.original_filename,
                    "relative_path": report.relative_path,
                    "metadata_source": "vendor_data_list.csv" if report.source_vendor not in {"malpedia", "thaicert"} else report.source_vendor,
                    "actor_group_is_not_campaign_label": True,
                },
            }, ensure_ascii=False) + "\n")

    metadata_fields = [
        "report_id", "original_filename", "relative_path", "title", "published_at",
        "source_vendor", "source_url", "actor_group", "author", "tags", "encoding",
        "content_hash", "entity_count", "attack_technique_count", "referenced_url_count",
    ]
    _write_csv(output_root / "report_metadata.csv", metadata_fields, ({
        "report_id": report.report_id,
        "original_filename": report.original_filename,
        "relative_path": report.relative_path,
        "title": report.title,
        "published_at": report.published_at.isoformat() if report.published_at else "",
        "source_vendor": report.source_vendor,
        "source_url": report.source_url or "",
        "actor_group": report.actor_group or "",
        "author": report.author or "",
        "tags": json.dumps(report.tags),
        "encoding": report.encoding,
        "content_hash": report.content_hash,
        "entity_count": len(report.entities),
        "attack_technique_count": len(report.attack_techniques),
        "referenced_url_count": len(report.referenced_urls),
    } for report in reports))

    pair_fields = [
        "report_a_id", "report_b_id", *FEATURE_COLUMNS, "label",
        "campaign_or_incident_group", "label_evidence", "feature_schema_version",
    ]
    _write_csv(output_root / "correlation_pairs.csv", pair_fields, pairs)
    _write_csv(output_root / "label_evidence.csv", [
        "report_a_id", "report_b_id", "proposed_label", "campaign_or_incident_group",
        "evidence", "review_status", "reviewer_id", "reviewed_at", "review_notes",
    ], ({
        "report_a_id": pair["report_a_id"],
        "report_b_id": pair["report_b_id"],
        "proposed_label": "uncertain",
        "campaign_or_incident_group": "",
        "evidence": pair["label_evidence"],
        "review_status": "pending",
        "reviewer_id": "",
        "reviewed_at": "",
        "review_notes": "",
    } for pair in pairs))

    stats = {
        "reports_with_usable_dates": sum(report.published_at is not None for report in reports),
        "reports_with_extracted_entities": sum(bool(report.entities) for report in reports),
        "reports_with_attack_references": sum(bool(report.attack_techniques) for report in reports),
        "candidate_pairs": len(pairs),
        "confirmed_positive_pairs": 0,
        "confirmed_negative_pairs": 0,
        "uncertain_pairs": len(pairs),
        "pairs_excluded_from_supervised_training": len(pairs),
        "missing_feature_counts": {
            name: sum(
                not bool(
                    pair["_feature_evidence"][
                        CANONICAL_BY_OUTPUT_NAME[name]
                    ].get("available")
                )
                for pair in pairs
            )
            for name in FEATURE_COLUMNS
        },
        "class_balance_for_supervised_training": {
            "positive": 0,
            "negative": 0,
            "uncertain_excluded": len(pairs),
        },
    }
    dataset_metadata = {
        **inventory,
        **stats,
        "feature_schema_version": "correlation-features-v1",
        "feature_columns": list(FEATURE_COLUMNS),
        "campaign_label_status": "unavailable",
        "training_ready": False,
        "training_blocker": (
            "The inspected dataset exposes actor/group organization and an evaluation "
            "URL list, but no reliable campaign/incident pair labels."
        ),
        "raw_data_modified": False,
    }
    (output_root / "dataset_metadata.json").write_text(
        json.dumps(dataset_metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return dataset_metadata


def run(dataset_root: Path, output_root: Path) -> dict[str, object]:
    reports, inventory = prepare_reports(dataset_root)
    pairs = build_uncertain_pairs(reports)
    return write_outputs(output_root, reports, inventory, pairs)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    metadata = run(args.dataset_root.resolve(), args.output_root.resolve())
    print(json.dumps({
        key: metadata[key]
        for key in (
            "original_report_files_discovered",
            "successfully_parsed_unique_reports",
            "exact_duplicates",
            "candidate_pairs",
            "confirmed_positive_pairs",
            "confirmed_negative_pairs",
            "uncertain_pairs",
            "training_ready",
        )
    }, indent=2))


if __name__ == "__main__":
    main()
