"""Run a CPU-only exploratory pair-level experiment on correlation-dataset-v3."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import platform
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.correlation.feature_schema import FEATURE_NAMES, FEATURE_SCHEMA_VERSION

FEATURE_COLUMNS = (
    "temporal_similarity",
    "entity_relationship_similarity",
    "behavioural_similarity",
    "attack_technique_similarity",
    "semantic_similarity",
    "knowledge_graph_similarity",
)
SEED = 20261117
THRESHOLDS = tuple(round(value, 2) for value in np.linspace(0.10, 0.90, 17))


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError(f"dataset is empty: {path}")
    return rows


def _validate_dataset(rows: list[dict[str, str]], source_path: Path) -> dict[str, Any]:
    expected_schema = FEATURE_SCHEMA_VERSION
    expected_columns = {
        "report_a_id",
        "report_b_id",
        *FEATURE_COLUMNS,
        "label",
        "feature_schema_version",
    }
    if not expected_columns.issubset(rows[0]):
        raise ValueError("v3 dataset is missing required pair or feature columns")
    labels = {row["label"] for row in rows}
    if labels != {"positive", "negative"}:
        raise ValueError(f"unexpected labels: {sorted(labels)}")
    if {row["feature_schema_version"] for row in rows} != {expected_schema}:
        raise ValueError("feature schema version mismatch")
    seen: set[tuple[str, str]] = set()
    duplicate_count = 0
    invalid_count = 0
    for row in rows:
        pair = (row["report_a_id"], row["report_b_id"])
        reverse = (pair[1], pair[0])
        if pair in seen or reverse in seen:
            duplicate_count += 1
        seen.add(pair)
        for column in FEATURE_COLUMNS:
            try:
                value = float(row[column])
            except ValueError:
                invalid_count += 1
                continue
            if not math.isfinite(value) or not 0.0 <= value <= 1.0:
                invalid_count += 1
    if duplicate_count or invalid_count:
        raise ValueError(
            f"dataset validation failed: duplicates={duplicate_count}, invalid_values={invalid_count}"
        )
    return {
        "row_count": len(rows),
        "label_counts": {
            label: sum(row["label"] == label for row in rows)
            for label in sorted(labels)
        },
        "duplicate_or_reverse_duplicate_count": duplicate_count,
        "invalid_feature_value_count": invalid_count,
        "feature_schema_version": expected_schema,
        "feature_columns": list(FEATURE_NAMES),
        "source_sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
    }


def _split(rows: list[dict[str, str]]) -> tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    indices = np.arange(len(rows))
    labels = np.array([row["label"] for row in rows])
    train_indices, remainder = train_test_split(
        indices,
        test_size=0.30,
        random_state=SEED,
        stratify=labels,
    )
    remainder_labels = labels[remainder]
    validation_indices, test_indices = train_test_split(
        remainder,
        test_size=0.50,
        random_state=SEED,
        stratify=remainder_labels,
    )
    assignments = {}
    for name, split_indices in (
        ("train", train_indices),
        ("validation", validation_indices),
        ("test", test_indices),
    ):
        assignments[name] = {
            "row_count": int(len(split_indices)),
            "label_counts": {
                label: int(sum(labels[split_indices] == label))
                for label in ("negative", "positive")
            },
            "indices": sorted(int(index) for index in split_indices),
        }
    return train_indices, validation_indices, test_indices, assignments


def _metrics(y_true: np.ndarray, probabilities: np.ndarray, threshold: float) -> dict[str, Any]:
    predictions = (probabilities >= threshold).astype(int)
    tn, fp, fn, tp = (int(value) for value in confusion_matrix(
        y_true, predictions, labels=[0, 1]
    ).ravel())
    return {
        "threshold": threshold,
        "precision": float(precision_score(y_true, predictions, zero_division=0)),
        "recall": float(recall_score(y_true, predictions, zero_division=0)),
        "f1": float(f1_score(y_true, predictions, zero_division=0)),
        "pr_auc": float(average_precision_score(y_true, probabilities)),
        "roc_auc": float(roc_auc_score(y_true, probabilities)),
        "confusion_matrix": [[tn, fp], [fn, tp]],
        "false_positive_rate": float(fp / (fp + tn)) if fp + tn else 0.0,
        "positive_predictions": int(predictions.sum()),
    }


def _tune_threshold(y_true: np.ndarray, probabilities: np.ndarray) -> tuple[float, dict[str, Any]]:
    candidates = [
        (threshold, _metrics(y_true, probabilities, threshold))
        for threshold in THRESHOLDS
    ]
    threshold, metrics = max(
        candidates,
        key=lambda item: (item[1]["f1"], item[1]["pr_auc"], item[1]["precision"], -item[0]),
    )
    return threshold, metrics


def _candidate_models() -> dict[str, list[tuple[str, Any]]]:
    candidates: dict[str, list[tuple[str, Any]]] = {
        "logistic_regression": [
            (
                f"C_{c}",
                Pipeline(
                    [
                        ("scaler", StandardScaler()),
                        (
                            "classifier",
                            LogisticRegression(
                                C=c,
                                class_weight="balanced",
                                max_iter=2000,
                                random_state=SEED,
                                solver="lbfgs",
                            ),
                        ),
                    ]
                ),
            )
            for c in (0.1, 1.0, 10.0)
        ],
        "random_forest": [
            (
                f"depth_{depth}_leaf_{leaf}",
                RandomForestClassifier(
                    class_weight="balanced_subsample",
                    max_depth=depth,
                    min_samples_leaf=leaf,
                    n_estimators=300,
                    n_jobs=-1,
                    random_state=SEED,
                ),
            )
            for depth, leaf in ((None, 1), (12, 1), (None, 3), (12, 3))
        ],
    }
    try:
        from xgboost import XGBClassifier
    except ImportError:
        return candidates
    candidates["xgboost"] = [
        (
            f"depth_{depth}_eta_{eta}",
            XGBClassifier(
                objective="binary:logistic",
                eval_metric="logloss",
                tree_method="hist",
                device="cpu",
                max_depth=depth,
                learning_rate=eta,
                n_estimators=300,
                subsample=0.9,
                colsample_bytree=0.9,
                scale_pos_weight=14519 / 2266,
                random_state=SEED,
                n_jobs=-1,
            ),
        )
        for depth, eta in ((3, 0.05), (5, 0.05), (3, 0.1))
    ]
    return candidates


def _positive_probability(model: Any, values: np.ndarray) -> np.ndarray:
    probabilities = model.predict_proba(values)
    return np.asarray(probabilities[:, 1], dtype=float)


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _report(
    output: Path,
    dataset: dict[str, Any],
    split: dict[str, Any],
    results: dict[str, Any],
    selected_model: str,
    started_at: str,
) -> None:
    lines = [
        "# Exploratory Training Report",
        "",
        "## Scope and warning",
        "",
        "This is an exploratory pair-level CPU experiment against weak/silver "
        "labels. Campaign-level leakage cannot be ruled out because a defensible "
        "campaign/incident grouping was unavailable. Test metrics may therefore "
        "be optimistic and must not be interpreted as campaign-independent or "
        "independently verified real-world accuracy.",
        "",
        "No original dataset, label, pair ID, or six-feature value was modified. "
        "No final production model is implied.",
        "",
        "## Configuration",
        "",
        f"- Dataset: `correlation-dataset-v3`",
        f"- Feature schema: `{dataset['feature_schema_version']}`",
        f"- Features: `{', '.join(dataset['feature_columns'])}`",
        f"- Random seed: `{SEED}`",
        "- Split: stratified pair-level 70% train / 15% validation / 15% test",
        "- CPU-only: yes",
        "- Missing-data handling: retained v3 neutral `0.5` materialization; no "
        "feature was dropped or filled with an arbitrary zero",
        f"- Started: `{started_at}`",
        "",
        "## Dataset and split counts",
        "",
        f"- Rows: {dataset['row_count']}",
        f"- Labels: {dataset['label_counts']}",
        f"- Source SHA-256: `{dataset['source_sha256']}`",
        "",
        "| Split | Rows | Negative | Positive |",
        "|---|---:|---:|---:|",
    ]
    for name in ("train", "validation", "test"):
        details = split[name]
        lines.append(
            f"| {name} | {details['row_count']} | "
            f"{details['label_counts']['negative']} | {details['label_counts']['positive']} |"
        )
    lines.extend(
        [
            "",
            "## Model comparison on held-out test data",
            "",
            "| Model | Precision | Recall | F1 | PR-AUC | ROC-AUC | FPR |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for name, result in results.items():
        if not isinstance(result, dict) or result.get("status") == "unavailable":
            continue
        test = result["test"]
        lines.append(
            f"| {name} | {test['precision']:.4f} | {test['recall']:.4f} | "
            f"{test['f1']:.4f} | {test['pr_auc']:.4f} | {test['roc_auc']:.4f} | "
            f"{test['false_positive_rate']:.4f} |"
        )
    lines.extend(["", "### Test thresholds and confusion matrices", ""])
    for name, result in results.items():
        if not isinstance(result, dict) or result.get("status") == "unavailable":
            continue
        test = result["test"]
        lines.append(
            f"- `{name}`: threshold `{test['threshold']:.2f}`, "
            f"confusion matrix `[[TN={test['confusion_matrix'][0][0]}, "
            f"FP={test['confusion_matrix'][0][1]}], "
            f"[FN={test['confusion_matrix'][1][0]}, "
            f"TP={test['confusion_matrix'][1][1]}]]`."
        )
    lines.extend(
        [
            "",
            "### Validation tuning results",
            "",
            "| Model | Selected candidate | Threshold | Validation F1 | Validation PR-AUC |",
            "|---|---|---:|---:|---:|",
        ]
    )
    for name, result in results.items():
        if (
            not isinstance(result, dict)
            or result.get("status") == "unavailable"
            or "validation" not in result
        ):
            continue
        validation = result["validation"]
        lines.append(
            f"| {name} | {result.get('candidate', 'majority baseline')} | "
            f"{validation['threshold']:.2f} | {validation['f1']:.4f} | "
            f"{validation['pr_auc']:.4f} |"
        )
    lines.extend(
        [
            "",
            f"Selected model by validation F1/PR-AUC: **{selected_model}**.",
            "Thresholds were selected on validation data only. The test set was "
            "read only for final evaluation.",
            "",
            "## Limitations",
            "",
            "- Labels are deterministic weak/silver labels, not independent ground truth.",
            "- Pair-level stratification does not prevent reports, campaigns, or incidents "
            "from appearing across partitions.",
            "- Campaign/incident grouping was tested and rejected because it produced "
            "transitive over-merging and explicit negative conflicts.",
            "- XGBoost is included only when installed; unavailable estimators are recorded "
            "in `metrics.json`.",
            "- Results do not establish campaign-independent generalisation or real-world "
            "campaign-correlation accuracy.",
            "",
            "## Artifacts",
            "",
            "- `models/`: versioned fitted model pipelines",
            "- `split_assignments.csv`: fixed-seed row assignments and labels",
            "- `preprocessing.json` and `preprocessing.joblib`: preprocessing metadata",
            "- `config.json`: reproducibility configuration",
            "- `metrics.json`: validation tuning and test metrics",
        ]
    )
    (output / "EXPLORATORY_TRAINING_REPORT.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def run(dataset_path: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(
            f"experiment directory already exists; choose a new version: {output}"
        )
    started_at = datetime.now(timezone.utc).isoformat()
    rows = _read_rows(dataset_path)
    dataset = _validate_dataset(rows, dataset_path)
    features = np.asarray(
        [[float(row[column]) for column in FEATURE_COLUMNS] for row in rows],
        dtype=np.float32,
    )
    labels = np.asarray([1 if row["label"] == "positive" else 0 for row in rows])
    train_indices, validation_indices, test_indices, split = _split(rows)
    output.mkdir(parents=True)
    (output / "models").mkdir()
    with (output / "split_assignments.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["row_index", "report_a_id", "report_b_id", "label", "split"],
        )
        writer.writeheader()
        split_by_index = {
            index: name
            for name, details in split.items()
            for index in details["indices"]
        }
        for index, row in enumerate(rows):
            writer.writerow(
                {
                    "row_index": index,
                    "report_a_id": row["report_a_id"],
                    "report_b_id": row["report_b_id"],
                    "label": row["label"],
                    "split": split_by_index[index],
                }
            )
    _write_json(
        output / "config.json",
        {
            "experiment_version": "exploratory-pair-v1",
            "dataset_path": str(dataset_path),
            "dataset_sha256": dataset["source_sha256"],
            "feature_columns": list(FEATURE_NAMES),
            "source_feature_columns": list(FEATURE_COLUMNS),
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "random_seed": SEED,
            "split_strategy": "stratified_pair_level_70_15_15",
            "campaign_grouping_available": False,
            "cpu_only": True,
            "python": sys.version,
            "platform": platform.platform(),
        },
    )
    _write_json(
        output / "preprocessing.json",
        {
            "feature_columns": list(FEATURE_NAMES),
            "missing_value_policy": "v3 materialized neutral 0.5; availability retained in v3 metadata",
            "zero_imputation": False,
            "logistic_regression": "StandardScaler fit on training rows only",
            "random_forest": "No feature transformation",
            "xgboost": "No feature transformation",
        },
    )
    models = _candidate_models()
    results: dict[str, Any] = {}
    for model_name, candidates in models.items():
        best: dict[str, Any] | None = None
        for candidate_name, model in candidates:
            started = time.perf_counter()
            model.fit(features[train_indices], labels[train_indices])
            elapsed = time.perf_counter() - started
            validation_probabilities = _positive_probability(
                model, features[validation_indices]
            )
            threshold, validation_metrics = _tune_threshold(
                labels[validation_indices], validation_probabilities
            )
            candidate = {
                "candidate": candidate_name,
                "model": model,
                "fit_seconds": elapsed,
                "validation": validation_metrics,
            }
            if best is None or (
                validation_metrics["f1"],
                validation_metrics["pr_auc"],
            ) > (
                best["validation"]["f1"],
                best["validation"]["pr_auc"],
            ):
                best = candidate
        assert best is not None
        test_probabilities = _positive_probability(best["model"], features[test_indices])
        best["test"] = _metrics(labels[test_indices], test_probabilities, best["validation"]["threshold"])
        best["threshold"] = best["validation"]["threshold"]
        model_path = output / "models" / f"{model_name}.joblib"
        joblib.dump(best["model"], model_path)
        results[model_name] = {
            key: value
            for key, value in best.items()
            if key != "model"
        }
    if "xgboost" not in results:
        results["xgboost"] = {
            "status": "unavailable",
            "reason": "xgboost is not installed in the selected CPU environment",
        }
    majority_probabilities = np.zeros(len(test_indices), dtype=float)
    results["majority_class_baseline"] = {
        "status": "evaluated",
        "validation": _metrics(labels[validation_indices], np.zeros(len(validation_indices)), 0.5),
        "test": _metrics(labels[test_indices], majority_probabilities, 0.5),
    }
    available_results = {
        name: value
        for name, value in results.items()
        if value.get("status") != "unavailable" and name != "majority_class_baseline"
    }
    selected_model = max(
        available_results,
        key=lambda name: (
            available_results[name]["validation"]["f1"],
            available_results[name]["validation"]["pr_auc"],
        ),
    )
    results["selected_model"] = selected_model
    results["generated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json(output / "metrics.json", results)
    preprocessing = {
        "feature_names": list(FEATURE_NAMES),
        "selected_model": selected_model,
        "models": {
            name: joblib.load(output / "models" / f"{name}.joblib")
            for name in available_results
        },
    }
    joblib.dump(preprocessing, output / "preprocessing.joblib")
    _report(output, dataset, split, results, selected_model, started_at)
    return {"output": str(output), "dataset": dataset, "split": split, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("data/correlation/processed/v3/silver_correlation_pairs.csv"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/correlation/experiments/exploratory_pair_v1"),
    )
    args = parser.parse_args()
    print(json.dumps(run(args.dataset, args.output), indent=2, default=str))


if __name__ == "__main__":
    main()
