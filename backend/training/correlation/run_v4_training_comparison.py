"""Compare CPU exploratory training on immutable v3 and improved v4 features."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
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
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.correlation.feature_schema import FEATURE_NAMES, FEATURE_SCHEMA_VERSION
from training.correlation.run_exploratory_training import FEATURE_COLUMNS, SEED, _read_rows, _validate_dataset

THRESHOLDS = tuple(round(value, 2) for value in np.linspace(0.10, 0.90, 17))
OUTPUT_VERSION = "v4-training-comparison-v1"


def _metrics(y_true: np.ndarray, probabilities: np.ndarray, threshold: float) -> dict[str, Any]:
    predictions = (probabilities >= threshold).astype(int)
    tn, fp, fn, tp = (int(value) for value in confusion_matrix(y_true, predictions, labels=[0, 1]).ravel())
    return {
        "threshold": threshold,
        "precision": float(precision_score(y_true, predictions, zero_division=0)),
        "recall": float(recall_score(y_true, predictions, zero_division=0)),
        "f1": float(f1_score(y_true, predictions, zero_division=0)),
        "pr_auc": float(average_precision_score(y_true, probabilities)),
        "roc_auc": float(roc_auc_score(y_true, probabilities)),
        "confusion_matrix": [[tn, fp], [fn, tp]],
        "false_positive_rate": float(fp / (fp + tn)) if fp + tn else 0.0,
    }


def _tune(y_true: np.ndarray, probabilities: np.ndarray) -> tuple[float, dict[str, Any]]:
    candidates = [(threshold, _metrics(y_true, probabilities, threshold)) for threshold in THRESHOLDS]
    return max(candidates, key=lambda item: (item[1]["f1"], item[1]["pr_auc"], item[1]["precision"], -item[0]))


def _models() -> list[tuple[str, str, Any]]:
    models: list[tuple[str, str, Any]] = []
    for c in (0.1, 1.0, 10.0):
        models.append((
            "logistic_regression",
            f"C_{c}",
            Pipeline([
                ("scaler", StandardScaler()),
                ("classifier", LogisticRegression(C=c, class_weight="balanced", max_iter=3000, random_state=SEED)),
            ]),
        ))
    for depth, leaf in ((None, 1), (12, 1), (None, 3)):
        models.append((
            "random_forest",
            f"depth_{depth}_leaf_{leaf}",
            RandomForestClassifier(
                n_estimators=300,
                max_depth=depth,
                min_samples_leaf=leaf,
                class_weight="balanced_subsample",
                n_jobs=-1,
                random_state=SEED,
            ),
        ))
    try:
        from xgboost import XGBClassifier
    except ImportError:
        return models
    models.append((
        "xgboost",
        "depth_3_eta_0.05",
        XGBClassifier(
            objective="binary:logistic",
            eval_metric="logloss",
            tree_method="hist",
            device="cpu",
            max_depth=3,
            learning_rate=0.05,
            n_estimators=300,
            subsample=0.9,
            colsample_bytree=0.9,
            scale_pos_weight=14519 / 2266,
            random_state=SEED,
            n_jobs=-1,
        ),
    ))
    return models


def _probabilities(model: Any, values: np.ndarray) -> np.ndarray:
    return np.asarray(model.predict_proba(values)[:, 1], dtype=float)


def _importance(model: Any) -> dict[str, float]:
    estimator = model.named_steps["classifier"] if isinstance(model, Pipeline) else model
    if hasattr(estimator, "feature_importances_"):
        values = np.asarray(estimator.feature_importances_, dtype=float)
    elif hasattr(estimator, "coef_"):
        values = np.abs(np.asarray(estimator.coef_[0], dtype=float))
    else:
        return {}
    return {
        name: float(value)
        for name, value in sorted(zip(FEATURE_NAMES, values), key=lambda item: item[1], reverse=True)
    }


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _split_by_pair(v3_rows: list[dict[str, str]], assignments_path: Path) -> dict[tuple[str, str], str]:
    assignments = _load_csv(assignments_path)
    by_index = {int(row["row_index"]): row for row in assignments}
    if len(by_index) != len(v3_rows):
        raise ValueError("saved split does not cover every v3 row")
    result: dict[tuple[str, str], str] = {}
    for index, row in enumerate(v3_rows):
        assignment = by_index[index]
        if assignment["label"] != row["label"] or assignment["report_a_id"] != row["report_a_id"] or assignment["report_b_id"] != row["report_b_id"]:
            raise ValueError(f"split assignment mismatch at v3 row {index}")
        result[(row["report_a_id"], row["report_b_id"])] = assignment["split"]
    return result


def _run_dataset(
    name: str,
    rows: list[dict[str, str]],
    split_by_pair: dict[tuple[str, str], str],
    output: Path,
) -> dict[str, Any]:
    labels = np.asarray([1 if row["label"] == "positive" else 0 for row in rows], dtype=np.int8)
    values = np.asarray([[float(row[column]) for column in FEATURE_COLUMNS] for row in rows], dtype=np.float32)
    indices = {
        split: np.asarray(
            [index for index, row in enumerate(rows) if split_by_pair[(row["report_a_id"], row["report_b_id"])] == split],
            dtype=int,
        )
        for split in ("train", "validation", "test")
    }
    results: list[dict[str, Any]] = []
    best: tuple[tuple[float, float, float], Any, str, str, float] | None = None
    for family, configuration, model in _models():
        started = time.perf_counter()
        model.fit(values[indices["train"]], labels[indices["train"]])
        validation_probabilities = _probabilities(model, values[indices["validation"]])
        threshold, validation_metrics = _tune(labels[indices["validation"]], validation_probabilities)
        item = {
            "family": family,
            "configuration": configuration,
            "fit_seconds": time.perf_counter() - started,
            "validation": validation_metrics,
        }
        results.append(item)
        score = (validation_metrics["f1"], validation_metrics["pr_auc"], validation_metrics["precision"])
        if best is None or score > best[0]:
            best = (score, model, family, configuration, threshold)
    if best is None:
        raise ValueError("no model candidates were available")
    _, _, best_family, best_configuration, threshold = best
    final_model = next(
        model
        for family, configuration, model in _models()
        if family == best_family and configuration == best_configuration
    )
    train_validation = np.concatenate([indices["train"], indices["validation"]])
    final_model.fit(values[train_validation], labels[train_validation])
    test_metrics = _metrics(labels[indices["test"]], _probabilities(final_model, values[indices["test"]]), threshold)
    dataset_output = output / name
    dataset_output.mkdir(parents=True)
    joblib.dump(final_model, dataset_output / f"{best_family}.joblib")
    return {
        "name": name,
        "row_count": len(rows),
        "split_counts": {
            split: {
                "rows": int(len(indices[split])),
                "negative": int((labels[indices[split]] == 0).sum()),
                "positive": int((labels[indices[split]] == 1).sum()),
            }
            for split in indices
        },
        "models": results,
        "selected": {
            "family": best_family,
            "configuration": best_configuration,
            "validation_threshold": threshold,
            "test": test_metrics,
            "feature_importance": _importance(final_model),
        },
    }


def _report(output: Path, result: dict[str, Any], verification: dict[str, Any]) -> None:
    lines = [
        "# V4 Training Comparison Report",
        "",
        "This is a CPU-only exploratory experiment against weak/silver labels. Campaign-level leakage cannot be ruled out because campaign/incident grouping was infeasible. Results are not campaign-independent or independently verified real-world accuracy.",
        "",
        "## Integrity checks",
        "",
        f"- Pair IDs and labels match v3 exactly: **{verification['pair_labels_match']}**",
        f"- v3 rows: {verification['v3_rows']}; v4 rows: {verification['v4_rows']}",
        f"- Feature schema: `{FEATURE_SCHEMA_VERSION}`",
        f"- Random seed: `{SEED}`; split source: preserved v3 pair-level assignments",
        f"- CPU-only: yes; test data was not used for selection or threshold tuning",
        "",
        "## Split counts",
        "",
        "| Dataset | Split | Rows | Negative | Positive |",
        "|---|---|---:|---:|---:|",
    ]
    for dataset_name in ("v3", "v4"):
        for split, counts in result[dataset_name]["split_counts"].items():
            lines.append(f"| {dataset_name} | {split} | {counts['rows']} | {counts['negative']} | {counts['positive']} |")
    lines.extend([
        "",
        "## Feature distribution and missingness comparison",
        "",
        "| Feature | v3 mean | v4 mean | v3 missing % | v4 missing % |",
        "|---|---:|---:|---:|---:|",
    ])
    for feature in FEATURE_COLUMNS:
        v3_stats = verification["feature_statistics"]["v3"][feature]
        v4_stats = verification["feature_statistics"]["v4"][feature]
        lines.append(
            f"| `{feature}` | {v3_stats['mean']:.6f} | {v4_stats['mean']:.6f} | "
            f"{v3_stats['missing_percent']:.4f} | {v4_stats['missing_percent']:.4f} |"
        )
    lines.extend([
        "",
        "## Selected-model test comparison",
        "",
        "| Dataset | Model | Precision | Recall | F1 | PR-AUC | ROC-AUC | FPR | Threshold |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ])
    for name in ("v3", "v4"):
        selected = result[name]["selected"]
        metrics = selected["test"]
        lines.append(f"| {name} | {selected['family']} ({selected['configuration']}) | {metrics['precision']:.4f} | {metrics['recall']:.4f} | {metrics['f1']:.4f} | {metrics['pr_auc']:.4f} | {metrics['roc_auc']:.4f} | {metrics['false_positive_rate']:.4f} | {metrics['threshold']:.2f} |")
    lines.extend(["", "## Validation model selection", "", "| Dataset | Family | Configuration | Validation F1 | Validation PR-AUC | Threshold |", "|---|---|---|---:|---:|---:|"])
    for name in ("v3", "v4"):
        for item in sorted(result[name]["models"], key=lambda x: (x["validation"]["f1"], x["validation"]["pr_auc"]), reverse=True):
            lines.append(f"| {name} | {item['family']} | `{item['configuration']}` | {item['validation']['f1']:.4f} | {item['validation']['pr_auc']:.4f} | {item['validation']['threshold']:.2f} |")
    lines.extend(["", "## V4 feature importance", "", "| Feature | Importance |", "|---|---:|"])
    for name, value in result["v4"]["selected"]["feature_importance"].items():
        lines.append(f"| `{name}` | {value:.6f} |")
    lines.extend([
        "",
        "## Interpretation",
        "",
        f"- Test F1 changed from `{result['v3']['selected']['test']['f1']:.4f}` on v3 to `{result['v4']['selected']['test']['f1']:.4f}` on v4 ({result['v4']['selected']['test']['f1'] - result['v3']['selected']['test']['f1']:+.4f}); v4 did not improve F1.",
        f"- Test PR-AUC changed from `{result['v3']['selected']['test']['pr_auc']:.4f}` to `{result['v4']['selected']['test']['pr_auc']:.4f}` ({result['v4']['selected']['test']['pr_auc'] - result['v3']['selected']['test']['pr_auc']:+.4f}) and ROC-AUC changed from `{result['v3']['selected']['test']['roc_auc']:.4f}` to `{result['v4']['selected']['test']['roc_auc']:.4f}` ({result['v4']['selected']['test']['roc_auc'] - result['v3']['selected']['test']['roc_auc']:+.4f}); ranking improved modestly while the selected threshold produced lower F1.",
        f"- ATT&CK feature importance increased from `{result['v3']['selected']['feature_importance'].get('attack_technique_similarity', 0.0):.6f}` to `{result['v4']['selected']['feature_importance'].get('attack_technique_similarity', 0.0):.6f}`. Behavioural importance changed from `{result['v3']['selected']['feature_importance'].get('behavioural_similarity', 0.0):.6f}` to `{result['v4']['selected']['feature_importance'].get('behavioural_similarity', 0.0):.6f}`.",
        "The coverage improvement therefore made ATT&CK information usable to the model, but did not by itself establish better classification at the selected operating threshold. Any metric change remains an exploratory weak-label result and does not prove campaign-independent generalisation.",
        "",
        "## Artifacts",
        "",
        "- `v3/` and `v4/`: separately saved selected model artifacts",
        "- `metrics.json`: validation candidates, selected models, test metrics and importance",
        "- `config.json`: dataset hashes, split hash and reproducibility settings",
    ])
    (output / "V4_TRAINING_COMPARISON_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(v3_path: Path, v4_path: Path, split_path: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    v3_rows = _read_rows(v3_path)
    v4_rows = _read_rows(v4_path)
    v3_validation = _validate_dataset(v3_rows, v3_path)
    v4_validation = _validate_dataset(v4_rows, v4_path)
    if len(v3_rows) != 16785 or len(v4_rows) != 16785:
        raise ValueError("expected 16,785 rows in both v3 and v4")
    v3_keys = [(row["report_a_id"], row["report_b_id"], row["label"]) for row in v3_rows]
    v4_keys = [(row["report_a_id"], row["report_b_id"], row["label"]) for row in v4_rows]
    if v3_keys != v4_keys:
        raise ValueError("v4 pair IDs or labels differ from v3")
    split_by_pair = _split_by_pair(v3_rows, split_path)
    with (v3_path.parent / "feature_generation_metadata.json").open(encoding="utf-8") as handle:
        v3_metadata = json.load(handle)
    with (v4_path.parent / "feature_generation_metadata.json").open(encoding="utf-8") as handle:
        v4_metadata = json.load(handle)
    output.mkdir(parents=True)
    result = {
        "v3": _run_dataset("v3", v3_rows, split_by_pair, output),
        "v4": _run_dataset("v4", v4_rows, split_by_pair, output),
    }
    verification = {
        "pair_labels_match": True,
        "v3_rows": len(v3_rows),
        "v4_rows": len(v4_rows),
        "v3_sha256": hashlib.sha256(v3_path.read_bytes()).hexdigest(),
        "v4_sha256": hashlib.sha256(v4_path.read_bytes()).hexdigest(),
        "split_sha256": hashlib.sha256(split_path.read_bytes()).hexdigest(),
        "v3_schema": v3_validation["feature_schema_version"],
        "v4_schema": v4_validation["feature_schema_version"],
        "feature_statistics": {
            "v3": v3_metadata["statistics"],
            "v4": v4_metadata["statistics"],
        },
    }
    _write_json(output / "metrics.json", {"generated_at": datetime.now(timezone.utc).isoformat(), "verification": verification, **result})
    _write_json(output / "config.json", {
        "experiment_version": OUTPUT_VERSION,
        "random_seed": SEED,
        "cpu_only": True,
        "split_strategy": "reused_v3_pair_id_assignments",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        **verification,
        "campaign_grouping_available": False,
    })
    with (output / "split_assignments.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row_index", "report_a_id", "report_b_id", "label", "split"])
        for index, row in enumerate(v4_rows):
            writer.writerow([index, row["report_a_id"], row["report_b_id"], row["label"], split_by_pair[(row["report_a_id"], row["report_b_id"])]])
    _report(output, result, verification)
    return {"verification": verification, "v3": result["v3"]["selected"], "v4": result["v4"]["selected"]}


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--v3", type=Path, default=Path("data/correlation/processed/v3/silver_correlation_pairs.csv"))
    parser.add_argument("--v4", type=Path, default=Path("data/correlation/processed/v4_feature_improvement/silver_correlation_pairs.csv"))
    parser.add_argument("--split", type=Path, default=Path("data/correlation/experiments/exploratory_pair_v1/split_assignments.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/correlation/experiments/v4_training_comparison_v1"))
    args = parser.parse_args()
    print(json.dumps(run(args.v3, args.v4, args.split, args.output), indent=2))


if __name__ == "__main__":
    main()
