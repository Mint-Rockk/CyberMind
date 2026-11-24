"""Recompute the canonical six features into an isolated v3 dataset."""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from app.correlation.service import calculate_features
from app.correlation.types import DocumentRepresentation
from app.core.config import get_settings
from app.graph.client import Neo4jClient
from app.correlation.feature_schema import FEATURE_NAMES, FEATURE_SCHEMA_VERSION
from app.correlation.behavioural import extract_behaviour_evidence

FEATURE_COLUMNS = (
    "temporal_similarity",
    "entity_relationship_similarity",
    "behavioural_similarity",
    "attack_technique_similarity",
    "semantic_similarity",
    "knowledge_graph_similarity",
)


def _read_jsonl(path: Path) -> dict[str, dict[str, object]]:
    with path.open(encoding="utf-8") as handle:
        return {str(row["report_id"]): row for row in map(json.loads, handle)}


def _read_embeddings(path: Path) -> dict[str, tuple[float, ...]]:
    result: dict[str, tuple[float, ...]] = {}
    with path.open(encoding="utf-8") as handle:
        for row in map(json.loads, handle):
            vector = tuple(float(value) for value in row["embedding"])
            if len(vector) != 384 or not all(math.isfinite(value) for value in vector):
                raise ValueError(f"invalid embedding for {row['report_id']}")
            result[str(row["report_id"])] = vector
    return result


def _parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed


def _graph_relationships(client: Neo4jClient, reports: dict[str, dict[str, object]]) -> dict[str, tuple[tuple[str, str, str], ...]]:
    rows = client.run(
        """
        MATCH (report:ThreatReport)
        OPTIONAL MATCH (report)-[relationship]->(target)
        WITH report, collect(
          CASE WHEN target IS NULL THEN NULL
          ELSE {label: labels(target)[0], type: type(relationship), id: target.stable_id}
          END
        ) AS relationships
        RETURN report.stable_id AS stable_id, report.evidence AS provenance,
          [item IN relationships WHERE item IS NOT NULL] AS relationships
        """
    )
    by_id: dict[str, tuple[tuple[str, str, str], ...]] = {}
    by_path = {
        str(report.get("relative_path")): report_id
        for report_id, report in reports.items()
    }
    for row in rows:
        provenance = {}
        if row.get("provenance"):
            try:
                provenance = json.loads(str(row["provenance"]))
            except json.JSONDecodeError:
                continue
        report_id = provenance.get("dataset_report_id")
        if not report_id:
            report_id = by_path.get(
                str(provenance.get("dataset_relative_path") or provenance.get("original_reference"))
            )
        if not report_id or report_id not in reports:
            continue
        relationships = tuple(
            (
                str(item["label"]).casefold(),
                str(item["type"]).casefold(),
                str(item["id"]),
            )
            for item in row["relationships"]
            if item.get("label") and item.get("type") and item.get("id")
        )
        by_id[str(report_id)] = tuple(sorted(set(relationships)))
    return by_id


def _representation(
    report: dict[str, object],
    embedding: tuple[float, ...],
    graph_relationships: tuple[tuple[str, str, str], ...],
    graph_available: bool,
) -> DocumentRepresentation:
    return DocumentRepresentation(
        published_at=_parse_datetime(report.get("published_at")),
        entities=tuple(
            str(item["normalized_name"])
            for item in report.get("entities", [])
            if item.get("normalized_name")
        ),
        behaviours=tuple(
            item.value for item in extract_behaviour_evidence(
                str(report.get("normalized_text") or "")
            )
        ),
        attack_techniques=tuple(str(value) for value in report.get("attack_techniques", [])),
        embedding=embedding,
        knowledge_graph_relationships=graph_relationships,
        metadata={"knowledge_graph_available": graph_available},
    )


def _stats(values: list[float], missing: int) -> dict[str, object]:
    return {
        "count": len(values),
        "missing_count": missing,
        "missing_percent": round(missing / len(values) * 100, 4),
        "zero_count": sum(value == 0.0 for value in values),
        "neutral_count": sum(value == 0.5 for value in values),
        "mean": round(mean(values), 8),
        "stddev": round(pstdev(values), 8),
        "minimum": min(values),
        "maximum": max(values),
    }


def recompute(processed: Path, output: Path) -> dict[str, object]:
    reports = _read_jsonl(processed / "normalized_reports.jsonl")
    embeddings = _read_embeddings(processed / "v2" / "report_embeddings.jsonl")
    with (processed / "v2" / "silver_correlation_pairs.csv").open(
        encoding="utf-8", newline=""
    ) as handle:
        pairs = list(csv.DictReader(handle))
    missing_embeddings = sorted(set(
        report_id for pair in pairs for report_id in (pair["report_a_id"], pair["report_b_id"])
    ) - set(embeddings))
    if missing_embeddings:
        raise ValueError(f"missing embeddings for {len(missing_embeddings)} reports")
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
    required_reports = {
        report_id for pair in pairs for report_id in (pair["report_a_id"], pair["report_b_id"])
    }
    uncovered = sorted(required_reports - graph.keys())
    if uncovered:
        raise RuntimeError(
            f"graph coverage incomplete for {len(uncovered)} pair reports; "
            "complete synchronization before creating v3"
        )

    output.mkdir(parents=True, exist_ok=True)
    feature_values: dict[str, list[float]] = {name: [] for name in FEATURE_COLUMNS}
    missing_counts: Counter[str] = Counter()
    by_label: dict[str, dict[str, list[float]]] = {}
    by_label_missing: dict[str, Counter[str]] = {}
    rows: list[dict[str, object]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for pair in pairs:
        key = (pair["report_a_id"], pair["report_b_id"])
        if key in seen_pairs or (key[1], key[0]) in seen_pairs:
            raise ValueError(f"duplicate or reverse-duplicate pair: {key}")
        seen_pairs.add(key)
        first_id, second_id = key
        first = _representation(
            reports[first_id], embeddings[first_id], graph[first_id], True
        )
        second = _representation(
            reports[second_id], embeddings[second_id], graph[second_id], True
        )
        vector = calculate_features(first, second)
        values = dict(zip(FEATURE_COLUMNS, vector.values, strict=True))
        label = str(pair["label"])
        by_label.setdefault(label, {name: [] for name in FEATURE_COLUMNS})
        by_label_missing.setdefault(label, Counter())
        for name in FEATURE_COLUMNS:
            value = float(values[name])
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                raise ValueError(f"invalid {name} value for {key}: {value}")
            feature_values[name].append(value)
            by_label[label][name].append(value)
            by_label.setdefault(label, {name: [] for name in FEATURE_COLUMNS})
            if not vector.evidence[FEATURE_NAMES[FEATURE_COLUMNS.index(name)]]["available"]:
                missing_counts[name] += 1
                by_label_missing[label][name] += 1
        rows.append({
            "report_a_id": first_id,
            "report_b_id": second_id,
            **values,
            "label": label,
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
        })

    with (output / "silver_correlation_pairs.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    shutil.copy2(processed / "label_evidence.csv", output / "label_evidence.csv")
    shutil.copy2(processed / "v2" / "report_embeddings.jsonl", output / "report_embeddings.jsonl")
    metadata = {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "dataset_version": "correlation-dataset-v3",
        "pair_count": len(rows),
        "report_count": len(required_reports),
        "label_counts": dict(Counter(row["label"] for row in rows)),
        "graph_report_coverage": len(graph),
        "knowledge_graph": {
            "neo4j_version": "5.26.5-community",
            "projection": "existing GraphSynchronizer stable-ID MERGE projection",
            "relationship_source": "evidence-backed persisted entity associations",
            "report_nodes": 12095,
            "provenance_report_nodes": 12095,
        },
        "behavioural_extractor_version": "deterministic_behaviour_lexicon_v1",
        "embedding": {
            "model_name": settings.embedding_model_name,
            "model_version": settings.embedding_model_version,
            "dimension": settings.embedding_dimension,
            "preprocessing_version": "whitespace-normalized-v1",
            "report_count": len(embeddings),
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
        "statistics_by_label": {
            label: {
                name: _stats(values[name], by_label_missing[label][name])
                for name in FEATURE_COLUMNS
            }
            for label, values in by_label.items()
        },
        "generated_at": datetime.now().astimezone().isoformat(),
        "source_silver": "v2/silver_correlation_pairs.csv",
        "original_labels_preserved": True,
    }
    (output / "feature_generation_metadata.json").write_text(
        json.dumps(metadata, indent=2), encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--processed", type=Path, default=Path("data/correlation/processed"))
    parser.add_argument("--output", type=Path, default=Path("data/correlation/processed/v3"))
    args = parser.parse_args()
    print(json.dumps(recompute(args.processed, args.output), indent=2))


if __name__ == "__main__":
    main()
