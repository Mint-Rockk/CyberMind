"""Recompute an isolated evidence-backed feature dataset from CTI report text."""

from __future__ import annotations

import argparse
import asyncio
import csv
import hashlib
import json
import math
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.attack.dataset import download_official_dataset
from app.attack.service import find_mapping_candidates
from app.correlation.behavioural import extract_behaviour_evidence
from app.correlation.feature_schema import FEATURE_NAMES, FEATURE_SCHEMA_VERSION
from app.correlation.service import calculate_features
from app.correlation.types import DocumentRepresentation
from app.core.config import get_settings
from app.graph.client import Neo4jClient
from training.correlation.recompute_v3 import (
    FEATURE_COLUMNS,
    _graph_relationships,
    _parse_datetime,
    _read_embeddings,
    _read_jsonl,
)

OUTPUT_VERSION = "correlation-dataset-v4-feature-improvement"
BEHAVIOUR_METHOD = "deterministic_behaviour_lexicon_v2"


def _feature_evidence(
    report: dict[str, Any],
    attack_candidates: list[Any],
    behaviour_evidence: tuple[Any, ...],
) -> dict[str, Any]:
    return {
        "report_id": report["report_id"],
        "source_reference": {
            "dataset": report.get("provenance", {}).get("dataset"),
            "relative_path": report.get("relative_path"),
            "source_url": report.get("source_url"),
        },
        "attack_techniques": [
            {
                "external_id": candidate.attack.external_id,
                "name": candidate.attack.name,
                "confidence": candidate.confidence,
                "method": candidate.method,
                "status": candidate.status,
                "evidence": candidate.evidence,
            }
            for candidate in sorted(attack_candidates, key=lambda item: item.attack.external_id)
        ],
        "behaviours": [
            {
                "value": item.value,
                "confidence": item.confidence,
                "method": item.extraction_method,
                "evidence_text": item.evidence_text,
                "start": item.start,
                "end": item.end,
            }
            for item in behaviour_evidence
        ],
    }


def _representation(
    report: dict[str, Any],
    embedding: tuple[float, ...],
    graph_relationships: tuple[tuple[str, str, str], ...],
    techniques: tuple[str, ...],
    behaviours: tuple[str, ...],
) -> DocumentRepresentation:
    return DocumentRepresentation(
        published_at=_parse_datetime(report.get("published_at")),
        entities=tuple(
            str(item["normalized_name"])
            for item in report.get("entities", [])
            if item.get("normalized_name")
        ),
        behaviours=behaviours,
        attack_techniques=techniques,
        embedding=embedding,
        knowledge_graph_relationships=graph_relationships,
        metadata={"knowledge_graph_available": True},
    )


def _stats(values: list[float], missing: int) -> dict[str, Any]:
    return {
        "count": len(values),
        "missing_count": missing,
        "missing_percent": round(missing / len(values) * 100, 4),
        "zero_count": sum(value == 0.0 for value in values),
        "neutral_count": sum(value == 0.5 for value in values),
        "mean": round(sum(values) / len(values), 8),
        "minimum": min(values),
        "maximum": max(values),
    }


def recompute(processed: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    reports = _read_jsonl(processed / "normalized_reports.jsonl")
    embeddings = _read_embeddings(processed / "v3" / "report_embeddings.jsonl")
    with (processed / "v3" / "silver_correlation_pairs.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        pairs = list(csv.DictReader(handle))
    required_reports = {
        report_id
        for pair in pairs
        for report_id in (pair["report_a_id"], pair["report_b_id"])
    }
    missing_embeddings = sorted(required_reports - set(embeddings))
    if missing_embeddings:
        raise ValueError(f"missing embeddings for {len(missing_embeddings)} reports")

    attack_dataset = asyncio.run(download_official_dataset())
    settings = get_settings()
    client = Neo4jClient(
        settings.neo4j_uri,
        settings.neo4j_user,
        settings.neo4j_password,
        settings.neo4j_database,
    )
    try:
        graph = _graph_relationships(client, reports)
    finally:
        client.close()
    if required_reports - set(graph):
        raise ValueError("graph coverage is incomplete for the v3 pair reports")

    extracted: dict[str, dict[str, Any]] = {}
    for report_id in sorted(required_reports):
        report = reports[report_id]
        text = f"{report.get('title', '')}\n{report.get('normalized_text', '')}"
        candidates, unsupported = find_mapping_candidates(text, attack_dataset, [])
        behaviours = extract_behaviour_evidence(str(report.get("normalized_text") or ""))
        extracted[report_id] = {
            "techniques": tuple(sorted(candidate.attack.external_id for candidate in candidates)),
            "attack_candidates": candidates,
            "unsupported_attack_references": unsupported,
            "behaviours": behaviours,
        }

    output.mkdir(parents=True)
    rows: list[dict[str, Any]] = []
    feature_values: dict[str, list[float]] = {name: [] for name in FEATURE_COLUMNS}
    missing_counts: Counter[str] = Counter()
    evidence_rows: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for pair in pairs:
        key = (pair["report_a_id"], pair["report_b_id"])
        if key in seen_pairs or (key[1], key[0]) in seen_pairs:
            raise ValueError(f"duplicate or reverse-duplicate pair: {key}")
        seen_pairs.add(key)
        first_id, second_id = key
        first_extracted, second_extracted = extracted[first_id], extracted[second_id]
        first = _representation(
            reports[first_id],
            embeddings[first_id],
            graph[first_id],
            first_extracted["techniques"],
            tuple(item.value for item in first_extracted["behaviours"]),
        )
        second = _representation(
            reports[second_id],
            embeddings[second_id],
            graph[second_id],
            second_extracted["techniques"],
            tuple(item.value for item in second_extracted["behaviours"]),
        )
        vector = calculate_features(first, second)
        values = dict(zip(FEATURE_COLUMNS, vector.values, strict=True))
        for name in FEATURE_COLUMNS:
            value = float(values[name])
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"invalid {name} value for {key}: {value}")
            feature_values[name].append(value)
            if not vector.evidence[FEATURE_NAMES[FEATURE_COLUMNS.index(name)]]["available"]:
                missing_counts[name] += 1
        rows.append({
            "report_a_id": first_id,
            "report_b_id": second_id,
            **values,
            "label": pair["label"],
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
        })
        evidence_rows.append({
            "report_a_id": first_id,
            "report_b_id": second_id,
            "label": pair["label"],
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "features": vector.evidence,
            "source_evidence": {
                "report_a": _feature_evidence(
                    reports[first_id],
                    first_extracted["attack_candidates"],
                    first_extracted["behaviours"],
                ),
                "report_b": _feature_evidence(
                    reports[second_id],
                    second_extracted["attack_candidates"],
                    second_extracted["behaviours"],
                ),
            },
        })

    with (output / "silver_correlation_pairs.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    with (output / "feature_evidence.jsonl").open("w", encoding="utf-8") as handle:
        for row in evidence_rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
    with (output / "report_extraction_evidence.jsonl").open(
        "w", encoding="utf-8"
    ) as handle:
        for report_id in sorted(extracted):
            handle.write(
                json.dumps(
                    _feature_evidence(
                        reports[report_id],
                        extracted[report_id]["attack_candidates"],
                        extracted[report_id]["behaviours"],
                    ),
                    sort_keys=True,
                )
                + "\n"
            )
    shutil.copy2(processed / "v3" / "label_evidence.csv", output / "label_evidence.csv")
    shutil.copy2(processed / "v3" / "report_embeddings.jsonl", output / "report_embeddings.jsonl")

    metadata = {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "dataset_version": OUTPUT_VERSION,
        "source_dataset": "correlation-dataset-v3",
        "pair_count": len(rows),
        "report_count": len(required_reports),
        "label_counts": dict(Counter(row["label"] for row in rows)),
        "original_labels_preserved": True,
        "pair_ids_preserved": True,
        "graph_report_coverage": len(graph),
        "attack_dataset": {
            "version": attack_dataset.version,
            "source": "MITRE ATT&CK official enterprise STIX dataset",
            "mapping_methods": ["explicit_attack_reference", "lexical_attack_name"],
            "entity_relationship_inference_used": False,
        },
        "behavioural_extractor_version": BEHAVIOUR_METHOD,
        "extraction_coverage": {
            "reports_with_attack_techniques": sum(
                bool(item["techniques"]) for item in extracted.values()
            ),
            "reports_with_behaviour_evidence": sum(
                bool(item["behaviours"]) for item in extracted.values()
            ),
            "reports_with_unsupported_attack_references": sum(
                bool(item["unsupported_attack_references"]) for item in extracted.values()
            ),
            "total_reports": len(extracted),
        },
        "missingness": {
            name: {
                "count": len(feature_values[name]),
                "missing_count": missing_counts[name],
                "missing_percent": round(
                    missing_counts[name] / len(feature_values[name]) * 100, 4
                ),
                "zero_count": sum(value == 0.0 for value in feature_values[name]),
                "neutral_count": sum(value == 0.5 for value in feature_values[name]),
            }
            for name in FEATURE_COLUMNS
        },
        "statistics": {
            name: _stats(feature_values[name], missing_counts[name])
            for name in FEATURE_COLUMNS
        },
        "generated_at": datetime.now().astimezone().isoformat(),
        "source_v3_sha256": hashlib.sha256(
            (processed / "v3" / "silver_correlation_pairs.csv").read_bytes()
        ).hexdigest(),
    }
    (output / "feature_generation_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed", type=Path, default=Path("data/correlation/processed"))
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/correlation/processed/v4_feature_improvement"),
    )
    args = parser.parse_args()
    print(json.dumps(recompute(args.processed, args.output), indent=2))


if __name__ == "__main__":
    main()
