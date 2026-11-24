"""Conservative weak supervision for CTI report-pair labels.

The output is provisional silver data, never manually verified ground truth.
Only explicit, cross-report evidence can produce a positive or negative vote.
Actor, malware, tool, vulnerability, and technique overlap alone produces an
uncertain vote.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from app.correlation.feature_schema import FEATURE_SCHEMA_VERSION

OUTPUT_FEATURES = (
    "temporal_similarity",
    "entity_relationship_similarity",
    "behavioural_similarity",
    "attack_technique_similarity",
    "semantic_similarity",
    "knowledge_graph_similarity",
)
LABELS = {"positive", "negative", "uncertain"}
CONFIDENCE_CATEGORIES = {"high", "medium", "low"}

CAMPAIGN_PATTERNS = (
    re.compile(
        r"\b(?:(?i:operation|campaign))\s+(?:named|called|known as|code[- ]named)?\s*"
        r"[\"'“]?([A-Z][A-Za-z0-9][A-Za-z0-9 _./-]{1,60}?)[\"'”]?"
        r"(?=\s+(?:campaign|operation|target|against|was|is|in|by|on|$))",
    ),
    re.compile(r"\b(?i:operation)\s+([A-Z][A-Za-z0-9_-]{2,50})\b"),
    re.compile(
        r"\b([A-Z][A-Za-z0-9_-]{2,50})\s+(?i:campaign|operation)\b",
    ),
)
CAMPAIGN_STOPWORDS = {
    "the", "this", "that", "a", "an", "used", "targeting", "against",
    "activity", "activities", "malware", "attack", "attacks", "incident",
    "operation", "campaign", "new", "latest", "ongoing", "malspam",
    "ransomware", "cybercrime", "espionage", "crimeware", "phishing",
    "watering", "hole", "big", "game", "hunting", "intrusion", "breach",
    "compromise", "id", "ids", "team", "each", "one", "recent", "first",
    "second", "wider", "skilled", "identified", "criminal",
}
ACTOR_LIKE_RE = re.compile(r"^(?:apt|ta|unc|fin|g\d{1,3})[- ]?\d{1,4}$", re.IGNORECASE)
INCIDENT_TERMS = re.compile(
    r"\b(?:incident|breach|intrusion|compromise|outbreak|attack|campaign|"
    r"operation|exfiltration|ransomware|espionage)\b",
    re.IGNORECASE,
)
CONFLICT_TERMS = re.compile(
    r"\b(?:conflicting attribution|attribution is unclear|uncertain attribution|"
    r"possibly|may be|could be|unconfirmed|disputed)\b",
    re.IGNORECASE,
)
UNRELATED_TERMS = re.compile(
    r"\b(?:unrelated|not related|separate campaign|different campaign|"
    r"distinct incident|independent incident)\b",
    re.IGNORECASE,
)
CVE_RE = re.compile(r"\bCVE-\d{4}-\d{4,7}\b", re.IGNORECASE)
HASH_RE = re.compile(r"\b(?:[a-f0-9]{32}|[a-f0-9]{40}|[a-f0-9]{64})\b", re.IGNORECASE)
IP_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
DOMAIN_RE = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}\b",
    re.IGNORECASE,
)
DATE_RE = re.compile(
    r"\b(?:20\d{2}[-/]\d{1,2}[-/]\d{1,2}|"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+\d{1,2},?\s+20\d{2})\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class EvidenceItem:
    value: str
    excerpt: str
    evidence_type: str


@dataclass(frozen=True)
class ReportEvidence:
    report_id: str
    text: str
    title: str
    source_vendor: str
    source_references: tuple[str, ...]
    published_at: datetime | None
    campaign_refs: tuple[EvidenceItem, ...]
    incident_refs: tuple[EvidenceItem, ...]
    distinctive_refs: tuple[EvidenceItem, ...]
    actor_names: tuple[str, ...]
    malware_names: tuple[str, ...]
    tool_names: tuple[str, ...]
    technique_names: tuple[str, ...]
    sector_names: tuple[str, ...]
    has_conflicting_attribution: bool
    has_unrelated_language: bool
    unrelated_refs: tuple[EvidenceItem, ...]


@dataclass(frozen=True)
class RuleVote:
    rule_id: str
    label: str
    confidence_category: str
    evidence_a: tuple[EvidenceItem, ...]
    evidence_b: tuple[EvidenceItem, ...]
    campaign_reference: str | None
    explanation: str


def _excerpt(text: str, start: int, end: int) -> str:
    left = max(text.rfind(".", 0, start) + 1, text.rfind("\n", 0, start) + 1)
    right_dot = text.find(".", end)
    right_line = text.find("\n", end)
    ends = [value for value in (right_dot, right_line) if value >= 0]
    right = min(ends) + 1 if ends else len(text)
    return text[left:right].strip()[:1000]


def _items(pattern: re.Pattern[str], text: str, evidence_type: str) -> tuple[EvidenceItem, ...]:
    result: dict[str, EvidenceItem] = {}
    for match in pattern.finditer(text):
        value = (match.group(1) if match.lastindex else match.group(0)).strip(" \t\r\n.,;:()[]{}\"'“”")
        normalized = re.sub(r"\s+", " ", value).casefold()
        if not normalized or normalized in CAMPAIGN_STOPWORDS or len(normalized) < 3:
            continue
        result.setdefault(
            normalized,
            EvidenceItem(value=value, excerpt=_excerpt(text, match.start(), match.end()), evidence_type=evidence_type),
        )
    return tuple(result.values())


def _entity_values(report: dict[str, Any], entity_types: set[str]) -> tuple[str, ...]:
    values = {
        str(item.get("normalized_name", "")).casefold()
        for item in report.get("entities", [])
        if item.get("type") in entity_types and item.get("normalized_name")
    }
    return tuple(sorted(values))


def extract_evidence(report: dict[str, Any]) -> ReportEvidence:
    text = str(report.get("normalized_text") or "")
    source_refs = []
    if report.get("source_url"):
        source_refs.append(str(report["source_url"]))
    source_refs.extend(str(value) for value in report.get("referenced_urls", []) if value)
    campaign_refs: list[EvidenceItem] = []
    for pattern in CAMPAIGN_PATTERNS:
        campaign_refs.extend(_items(pattern, text, "explicit_campaign_reference"))
    campaign_refs = [
        item for item in {
            item.value.casefold(): item for item in campaign_refs
        }.values()
        if not ACTOR_LIKE_RE.match(item.value.strip())
    ]
    incident_refs = list(_items(INCIDENT_TERMS, text, "incident_context"))
    distinctive: list[EvidenceItem] = []
    for pattern, kind in (
        (CVE_RE, "cve"),
        (HASH_RE, "file_hash"),
        (IP_RE, "ip_address"),
        (DOMAIN_RE, "domain"),
    ):
        values = _items(pattern, text, kind)
        if kind == "domain":
            values = tuple(
                item for item in values
                if item.value.casefold().rsplit(".", 1)[-1] not in {
                    "exe", "dll", "js", "vbs", "bat", "ps1", "hta", "doc",
                    "docx", "pdf", "zip", "rar", "txt",
                }
            )
        distinctive.extend(values)
    unrelated_refs = _items(UNRELATED_TERMS, text, "explicit_unrelated_statement")
    published_at = None
    if report.get("published_at"):
        try:
            published_at = datetime.fromisoformat(str(report["published_at"]).replace("Z", "+00:00"))
        except ValueError:
            published_at = None
    return ReportEvidence(
        report_id=str(report["report_id"]),
        text=text,
        title=str(report.get("title") or ""),
        source_vendor=str(report.get("source_vendor") or ""),
        source_references=tuple(dict.fromkeys(source_refs)),
        published_at=published_at,
        campaign_refs=tuple(campaign_refs),
        incident_refs=tuple(incident_refs),
        distinctive_refs=tuple(distinctive),
        actor_names=_entity_values(report, {"threat_actor", "apt_group", "actor"}),
        malware_names=_entity_values(report, {"malware", "ransomware"}),
        tool_names=_entity_values(report, {"tool"}),
        technique_names=_entity_values(report, {"attack_reference"}),
        sector_names=_entity_values(report, {"sector"}),
        has_conflicting_attribution=bool(CONFLICT_TERMS.search(text)),
        has_unrelated_language=bool(unrelated_refs),
        unrelated_refs=unrelated_refs,
    )


def _by_value(items: Iterable[EvidenceItem]) -> dict[str, EvidenceItem]:
    return {item.value.casefold(): item for item in items}


def _shared_items(
    first: Iterable[EvidenceItem], second: Iterable[EvidenceItem]
) -> tuple[EvidenceItem, ...]:
    left, right = _by_value(first), _by_value(second)
    return tuple(left[key] for key in sorted(left.keys() & right.keys()))


def _shared_pairs(
    first: Iterable[EvidenceItem], second: Iterable[EvidenceItem]
) -> tuple[tuple[EvidenceItem, EvidenceItem], ...]:
    left, right = _by_value(first), _by_value(second)
    return tuple((left[key], right[key]) for key in sorted(left.keys() & right.keys()))


def _date_gap_days(first: ReportEvidence, second: ReportEvidence) -> int | None:
    if first.published_at is None or second.published_at is None:
        return None
    return abs((first.published_at - second.published_at).days)


def positive_votes(first: ReportEvidence, second: ReportEvidence) -> list[RuleVote]:
    votes: list[RuleVote] = []
    shared_campaigns = _shared_pairs(first.campaign_refs, second.campaign_refs)
    if shared_campaigns:
        evidence_a = (shared_campaigns[0][0],)
        evidence_b = (shared_campaigns[0][1],)
        campaign = evidence_a[0].value
        votes.append(RuleVote(
            "P1", "positive", "high", evidence_a, evidence_b, campaign,
            "Both reports explicitly reference the same named campaign or operation.",
        ))
        if first.source_vendor and second.source_vendor and first.source_vendor != second.source_vendor:
            votes.append(RuleVote(
                "P3", "positive", "high", evidence_a, evidence_b, campaign,
                "Independent source vendors explicitly reference the same named operation.",
            ))

    shared_distinctive = _shared_pairs(first.distinctive_refs, second.distinctive_refs)
    distinctive_types = {left.evidence_type for left, _ in shared_distinctive}
    if (
        len(shared_distinctive) >= 2
        and len(distinctive_types) >= 2
        and any(kind in distinctive_types for kind in {"cve", "file_hash", "ip_address"})
        and first.incident_refs
        and second.incident_refs
    ):
        gap = _date_gap_days(first, second)
        if gap is not None and gap <= 90:
            evidence_a = tuple(left for left, _ in shared_distinctive)
            evidence_b = tuple(right for _, right in shared_distinctive)
            votes.append(RuleVote(
                "P2", "positive", "high", evidence_a, evidence_b, None,
                "Both reports contain at least two distinctive indicators and incident context within a 90-day window.",
            ))
    return votes


def negative_votes(first: ReportEvidence, second: ReportEvidence) -> list[RuleVote]:
    votes: list[RuleVote] = []
    left = _by_value(first.campaign_refs)
    right = _by_value(second.campaign_refs)
    if len(left) == 1 and len(right) == 1 and not (left.keys() & right.keys()):
        if not _shared_items(first.distinctive_refs, second.distinctive_refs):
            votes.append(RuleVote(
                "N1", "negative", "high",
                tuple(left.values()), tuple(right.values()), None,
                "Each report explicitly names a different campaign or operation and no distinctive indicator is shared.",
            ))
    gap = _date_gap_days(first, second)
    if (
        len(left) == 1
        and len(right) == 1
        and not (left.keys() & right.keys())
        and gap is not None
        and gap > 365
        and first.incident_refs
        and second.incident_refs
        and not _shared_items(first.distinctive_refs, second.distinctive_refs)
    ):
        votes.append(RuleVote(
            "N2", "negative", "medium",
            tuple(left.values()), tuple(right.values()), None,
            "Explicitly different named incidents are separated by more than one year with no shared distinctive evidence.",
        ))
    if first.unrelated_refs and second.unrelated_refs:
        votes.append(RuleVote(
            "N3", "negative", "medium", first.unrelated_refs, second.unrelated_refs, None,
            "A report explicitly uses unrelated/separate-incident language.",
        ))
    return votes


def uncertain_rule(first: ReportEvidence, second: ReportEvidence, votes: list[RuleVote]) -> RuleVote:
    if any(v.label == "positive" for v in votes) and any(v.label == "negative" for v in votes):
        rule_id, explanation = "U6", "Positive and negative deterministic rules conflict; the pair remains uncertain."
    elif not first.text.strip() or not second.text.strip() or len(first.text) < 100 or len(second.text) < 100:
        rule_id, explanation = "U7", "One or both reports have missing or incomplete text."
    elif first.has_conflicting_attribution or second.has_conflicting_attribution:
        rule_id, explanation = "U6", "Attribution language is conflicting or explicitly uncertain."
    elif set(first.actor_names) & set(second.actor_names):
        rule_id, explanation = "U1", "The reports share actor attribution only; actor overlap is not campaign ground truth."
    elif set(first.malware_names) & set(second.malware_names):
        rule_id, explanation = "U2", "The reports share malware only; malware overlap is not campaign ground truth."
    elif set(first.technique_names) & set(second.technique_names):
        rule_id, explanation = "U3", "The reports share ATT&CK technique references only."
    else:
        rule_id, explanation = "U5", "Available evidence is insufficient to establish a campaign relationship."
    return RuleVote(rule_id, "uncertain", "low", (), (), None, explanation)


def classify_pair(first: ReportEvidence, second: ReportEvidence) -> dict[str, Any]:
    votes = positive_votes(first, second) + negative_votes(first, second)
    positive = [vote for vote in votes if vote.label == "positive"]
    negative = [vote for vote in votes if vote.label == "negative"]
    conflict = bool(positive and negative)
    if conflict or not votes:
        fallback = uncertain_rule(first, second, votes)
        votes_for_record = votes + [fallback]
        label = "uncertain"
        confidence = "low"
    elif positive:
        strongest = max(positive, key=lambda vote: {"high": 3, "medium": 2, "low": 1}[vote.confidence_category])
        votes_for_record = votes
        label = "positive"
        confidence = strongest.confidence_category
    else:
        strongest = max(negative, key=lambda vote: {"high": 3, "medium": 2, "low": 1}[vote.confidence_category])
        votes_for_record = votes
        label = "negative"
        confidence = strongest.confidence_category
    evidence_a: list[EvidenceItem] = []
    evidence_b: list[EvidenceItem] = []
    campaigns: list[str] = []
    for vote in votes_for_record:
        evidence_a.extend(vote.evidence_a)
        evidence_b.extend(vote.evidence_b)
        if vote.campaign_reference:
            campaigns.append(vote.campaign_reference)
    evidence_a = list({(item.evidence_type, item.value.casefold()): item for item in evidence_a}.values())
    evidence_b = list({(item.evidence_type, item.value.casefold()): item for item in evidence_b}.values())
    return {
        "proposed_label": label,
        "confidence_category": confidence,
        "labelling_method": "deterministic_weak_supervision",
        "matched_rules": [vote.rule_id for vote in votes_for_record],
        "evidence_from_report_a": [item.__dict__ for item in evidence_a],
        "evidence_from_report_b": [item.__dict__ for item in evidence_b],
        "contradictory_evidence": [vote.explanation for vote in votes if vote.label != label],
        "source_references": sorted(set(first.source_references + second.source_references)),
        "campaign_reference": sorted(set(campaigns))[0] if campaigns else None,
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "label_generation_timestamp": datetime.now(timezone.utc).isoformat(),
        "conflict": conflict,
        "explanation": "; ".join(vote.explanation for vote in votes_for_record),
    }


def _load_reports(path: Path) -> dict[str, dict[str, Any]]:
    reports: dict[str, dict[str, Any]] = {}
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                item = json.loads(line)
                reports[str(item["report_id"])] = item
    return reports


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _pair_key(row: dict[str, str]) -> tuple[str, str]:
    return tuple(sorted((row["report_a_id"], row["report_b_id"])))


def _write_header(path: Path, fields: list[str]) -> csv.DictWriter:
    handle = path.open("w", encoding="utf-8", newline="")
    writer = csv.DictWriter(handle, fieldnames=fields)
    writer.writeheader()
    writer._cybermind_handle = handle  # type: ignore[attr-defined]
    return writer


def _close_writer(writer: csv.DictWriter) -> None:
    handle = getattr(writer, "_cybermind_handle", None)
    if handle:
        handle.close()


def run(
    *,
    processed_root: Path,
    output_root: Path,
    validation_sample_size: int = 100,
) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    reports = _load_reports(processed_root / "normalized_reports.jsonl")
    evidence = {report_id: extract_evidence(report) for report_id, report in reports.items()}
    all_fields = [
        "report_a_id", "report_b_id", "proposed_label", "confidence_category",
        "labelling_method", "matched_rules", "evidence_from_report_a",
        "evidence_from_report_b", "contradictory_evidence", "source_references",
        "campaign_reference", "feature_schema_version", "label_generation_timestamp",
    ]
    silver_fields = ["report_a_id", "report_b_id", *OUTPUT_FEATURES, "label", "feature_schema_version"]
    weak_fields = ["report_a_id", "report_b_id", "proposed_label", "confidence_category", "matched_rules", "campaign_reference"]
    for path in (output_root / "silver_labels.csv", output_root / "medium_confidence_labels.csv", output_root / "uncertain_pairs.csv", output_root / "labelling_evidence.csv"):
        if path.exists():
            path.unlink()
    evidence_writer = _write_header(output_root / "labelling_evidence.csv", all_fields)
    silver_writer = _write_header(output_root / "silver_labels.csv", all_fields)
    medium_writer = _write_header(output_root / "medium_confidence_labels.csv", all_fields)
    uncertain_writer = _write_header(output_root / "uncertain_pairs.csv", all_fields)
    silver_pairs_writer = _write_header(processed_root / "silver_correlation_pairs.csv", silver_fields)
    sample_path = output_root / "validation_sample.csv"
    sample_writer = _write_header(sample_path, all_fields)
    stats: Counter[str] = Counter()
    source_vendors: set[str] = set()
    campaigns: set[str] = set()
    seen_pairs: set[tuple[str, str]] = set()
    sample_count = 0
    complete_evidence = 0
    feature_rows = 0

    with (processed_root / "correlation_pairs.csv").open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            pair_key = _pair_key(row)
            stats["total_pairs_analysed"] += 1
            if pair_key in seen_pairs:
                stats["duplicate_pairs"] += 1
                continue
            seen_pairs.add(pair_key)
            first, second = evidence.get(row["report_a_id"]), evidence.get(row["report_b_id"])
            if first is None or second is None:
                result = {
                    "proposed_label": "uncertain",
                    "confidence_category": "low",
                    "labelling_method": "deterministic_weak_supervision",
                    "matched_rules": ["U7"],
                    "evidence_from_report_a": [],
                    "evidence_from_report_b": [],
                    "contradictory_evidence": [],
                    "source_references": [],
                    "campaign_reference": None,
                    "feature_schema_version": FEATURE_SCHEMA_VERSION,
                    "label_generation_timestamp": datetime.now(timezone.utc).isoformat(),
                }
                stats["missing_report_content"] += 1
            else:
                result = classify_pair(first, second)
                source_vendors.update(value for value in (first.source_vendor, second.source_vendor) if value)
            result.update({"report_a_id": row["report_a_id"], "report_b_id": row["report_b_id"]})
            evidence_a = result["evidence_from_report_a"]
            evidence_b = result["evidence_from_report_b"]
            if evidence_a and evidence_b and result["source_references"]:
                complete_evidence += 1
            label = result["proposed_label"]
            confidence = result["confidence_category"]
            stats[f"{label}_labels"] += 1
            stats[f"{confidence}_confidence_labels"] += 1
            if label == "positive" and confidence == "high":
                stats["high_positive_labels"] += 1
            if label == "negative" and confidence == "high":
                stats["high_negative_labels"] += 1
            if result.get("conflict"):
                stats["conflicting_labels"] += 1
            if result.get("campaign_reference"):
                campaigns.add(result["campaign_reference"])
            output_row = {
                **result,
                "matched_rules": _json(result["matched_rules"]),
                "evidence_from_report_a": _json(evidence_a),
                "evidence_from_report_b": _json(evidence_b),
                "contradictory_evidence": _json(result["contradictory_evidence"]),
                "source_references": _json(result["source_references"]),
            }
            evidence_writer.writerow({field: output_row.get(field, "") for field in all_fields})
            eligible_high = (
                label in {"positive", "negative"}
                and confidence == "high"
                and bool(evidence_a)
                and bool(evidence_b)
                and bool(result["source_references"])
            )
            if eligible_high:
                silver_writer.writerow({field: output_row.get(field, "") for field in all_fields})
                if first is not None and second is not None:
                    silver_pairs_writer.writerow({
                        "report_a_id": row["report_a_id"],
                        "report_b_id": row["report_b_id"],
                        **{feature: row[feature] for feature in OUTPUT_FEATURES},
                        "label": label,
                        "feature_schema_version": FEATURE_SCHEMA_VERSION,
                    })
                    feature_rows += 1
                stats["eligible_high_confidence_labels"] += 1
            elif label in {"positive", "negative"} and confidence == "medium":
                medium_writer.writerow({field: output_row.get(field, "") for field in all_fields})
            else:
                if label in {"positive", "negative"} and confidence == "high":
                    stats["high_confidence_incomplete_evidence"] += 1
                uncertain_writer.writerow({field: output_row.get(field, "") for field in all_fields})
            if sample_count < validation_sample_size:
                sample_writer.writerow({field: output_row.get(field, "") for field in all_fields})
                sample_count += 1

    for writer in (evidence_writer, silver_writer, medium_writer, uncertain_writer, silver_pairs_writer, sample_writer):
        _close_writer(writer)
    stats["high_confidence_labels"] = stats["high_confidence_labels"]
    stats["medium_confidence_labels"] = stats["medium_confidence_labels"]
    stats["low_confidence_labels"] = stats["low_confidence_labels"]
    stats["evidence_complete_pairs"] = complete_evidence
    stats["distinct_campaign_references"] = len(campaigns)
    stats["distinct_report_sources"] = len(source_vendors)
    stats["reverse_duplicate_pairs"] = 0
    stats["feature_rows_in_silver_dataset"] = feature_rows
    stats["class_balance"] = {
        "positive": stats["positive_labels"],
        "negative": stats["negative_labels"],
        "uncertain": stats["uncertain_labels"],
    }
    stats["independent_ground_truth_available"] = False
    stats["quality_independently_established"] = False
    stats["training_ready"] = (
        stats["high_positive_labels"] > 0
        and stats["high_negative_labels"] > 0
        and feature_rows == stats["positive_labels"] + stats["negative_labels"]
        and stats["independent_ground_truth_available"]
    )
    stats["llm_assisted_labels"] = 0
    stats["llm_provider_configured"] = False
    stats["configuration"] = {
        "rules_version": "weak-supervision-v1",
        "only_high_confidence_labels_enter_silver": True,
        "actor_only_is_uncertain": True,
        "same_evidence_not_double_counted": True,
        "llm_enabled": False,
        "llm_max_pairs": 0,
    }
    (output_root / "labelling_statistics.json").write_text(
        json.dumps(dict(stats), indent=2, default=int) + "\n", encoding="utf-8"
    )
    (output_root / "labelling_configuration.json").write_text(
        json.dumps(stats["configuration"], indent=2) + "\n", encoding="utf-8"
    )
    return dict(stats)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--validation-sample-size", type=int, default=100)
    args = parser.parse_args()
    stats = run(
        processed_root=args.processed_root.resolve(),
        output_root=args.output_root.resolve(),
        validation_sample_size=args.validation_sample_size,
    )
    print(json.dumps({
        key: stats.get(key)
        for key in (
            "total_pairs_analysed", "positive_labels", "negative_labels",
            "uncertain_labels", "high_confidence_labels",
            "medium_confidence_labels", "low_confidence_labels",
            "conflicting_labels", "training_ready",
        )
    }, indent=2, default=int))


if __name__ == "__main__":
    main()
