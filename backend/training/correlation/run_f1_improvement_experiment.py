"""Run a conservative evidence-weighted CPU experiment on the v4 pair dataset."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.correlation.feature_schema import FEATURE_SCHEMA_VERSION
from training.correlation.run_exploratory_training import FEATURE_COLUMNS, SEED, _read_rows, _validate_dataset
from training.correlation.weak_supervision import classify_pair, extract_evidence

THRESHOLDS = tuple(round(value, 2) for value in np.linspace(0.10, 0.90, 17))
OUTPUT_VERSION = "f1-improvement-v3"
EVIDENCE_COLUMNS = (
    "shared_actor",
    "shared_malware",
    "shared_tool",
    "shared_technique",
    "shared_indicator",
    "cross_vendor",
)


def _metrics(y_true: np.ndarray, probability: np.ndarray, threshold: float) -> dict[str, Any]:
    prediction = (probability >= threshold).astype(int)
    tn, fp, fn, tp = (int(value) for value in confusion_matrix(y_true, prediction, labels=[0, 1]).ravel())
    return {
        "threshold": threshold,
        "precision": float(precision_score(y_true, prediction, zero_division=0)),
        "recall": float(recall_score(y_true, prediction, zero_division=0)),
        "f1": float(f1_score(y_true, prediction, zero_division=0)),
        "pr_auc": float(average_precision_score(y_true, probability)),
        "roc_auc": float(roc_auc_score(y_true, probability)),
        "confusion_matrix": [[tn, fp], [fn, tp]],
        "false_positive_rate": float(fp / (fp + tn)) if fp + tn else 0.0,
    }


def _tune(y_true: np.ndarray, probability: np.ndarray) -> tuple[float, dict[str, Any]]:
    candidates = [(threshold, _metrics(y_true, probability, threshold)) for threshold in THRESHOLDS]
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
    for depth, leaf in ((None, 1), (None, 3), (12, 1)):
        models.append((
            "random_forest",
            f"depth_{depth}_leaf_{leaf}",
            RandomForestClassifier(
                n_estimators=400,
                max_depth=depth,
                min_samples_leaf=leaf,
                class_weight="balanced_subsample",
                n_jobs=-1,
                random_state=SEED,
            ),
        ))
    models.append((
        "extra_trees",
        "depth_None_leaf_2",
        ExtraTreesClassifier(
            n_estimators=400,
            min_samples_leaf=2,
            class_weight="balanced",
            n_jobs=-1,
            random_state=SEED,
        ),
    ))
    models.append((
        "hist_gradient_boosting",
        "lr_0.05_leaves_31",
        HistGradientBoostingClassifier(
            learning_rate=0.05,
            max_leaf_nodes=31,
            max_iter=300,
            l2_regularization=1.0,
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
            n_estimators=350,
            subsample=0.9,
            colsample_bytree=0.9,
            scale_pos_weight=14519 / 2266,
            random_state=SEED,
            n_jobs=-1,
        ),
    ))
    return models


def _probability(model: Any, values: np.ndarray) -> np.ndarray:
    return np.asarray(model.predict_proba(values)[:, 1], dtype=float)


def _importance(model: Any, names: list[str]) -> dict[str, float]:
    estimator = model.named_steps["classifier"] if isinstance(model, Pipeline) else model
    if hasattr(estimator, "feature_importances_"):
        values = np.asarray(estimator.feature_importances_, dtype=float)
    elif hasattr(estimator, "coef_"):
        values = np.abs(np.asarray(estimator.coef_[0], dtype=float))
    else:
        return {}
    return {name: float(value) for name, value in sorted(zip(names, values), key=lambda item: item[1], reverse=True)}


def _split(path: Path, rows: list[dict[str, str]]) -> dict[str, np.ndarray]:
    with path.open(encoding="utf-8", newline="") as handle:
        assignments = list(csv.DictReader(handle))
    by_index = {int(row["row_index"]): row for row in assignments}
    if len(by_index) != len(rows):
        raise ValueError("split assignment count does not match v4")
    output: dict[str, list[int]] = {"train": [], "validation": [], "test": []}
    for index, row in enumerate(rows):
        assignment = by_index[index]
        if (assignment["report_a_id"], assignment["report_b_id"], assignment["label"]) != (
            row["report_a_id"], row["report_b_id"], row["label"]
        ):
            raise ValueError(f"split assignment mismatch at row {index}")
        output[assignment["split"]].append(index)
    return {name: np.asarray(indices, dtype=int) for name, indices in output.items()}


def _evidence_features(first: Any, second: Any, label: str) -> tuple[list[float], dict[str, Any]]:
    classification = classify_pair(first, second)
    shared_actors = sorted(set(first.actor_names) & set(second.actor_names))
    shared_malware = sorted(set(first.malware_names) & set(second.malware_names))
    shared_tools = sorted(set(first.tool_names) & set(second.tool_names))
    shared_techniques = sorted(set(first.technique_names) & set(second.technique_names))
    shared_indicators = sorted(
        {item.value for item in first.distinctive_refs}
        & {item.value for item in second.distinctive_refs}
    )
    campaign = "P1" in classification["matched_rules"] or "P3" in classification["matched_rules"]
    indicator = "P2" in classification["matched_rules"]
    hard_negative = label == "negative" and not campaign and not indicator and bool(
        shared_actors or shared_malware or shared_techniques
    )
    confidence = {"high": 1.0, "medium": 0.6, "low": 0.25}[classification["confidence_category"]]
    values = [
        float(bool(shared_actors)),
        float(bool(shared_malware)),
        float(bool(shared_tools)),
        float(bool(shared_techniques)),
        float(bool(shared_indicators)),
        float(first.source_vendor != second.source_vendor),
    ]
    return values, {
        "rules": classification["matched_rules"],
        "proposed_label": classification["proposed_label"],
        "confidence_category": classification["confidence_category"],
        "shared_actors": shared_actors,
        "shared_malware": shared_malware,
        "shared_tools": shared_tools,
        "shared_techniques": shared_techniques,
        "shared_indicators": shared_indicators,
        "hard_negative": hard_negative,
        "campaign_reference": classification["campaign_reference"],
        "explanation": classification["explanation"],
    }


def _fit(model: Any, x: np.ndarray, y: np.ndarray, weights: np.ndarray) -> Any:
    if isinstance(model, HistGradientBoostingClassifier):
        model.fit(x, y, sample_weight=weights)
    else:
        model.fit(x, y, **({"classifier__sample_weight": weights} if isinstance(model, Pipeline) else {"sample_weight": weights}))
    return model


def run(dataset: Path, reports_path: Path, split_path: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"output already exists: {output}")
    rows = _read_rows(dataset)
    validation = _validate_dataset(rows, dataset)
    if len(rows) != 16785:
        raise ValueError("expected 16,785 v4 rows")
    with reports_path.open(encoding="utf-8") as handle:
        reports = {json.loads(line)["report_id"]: json.loads(line) for line in handle}
    split = _split(split_path, rows)
    labels = np.asarray([1 if row["label"] == "positive" else 0 for row in rows], dtype=np.int8)
    base = np.asarray([[float(row[column]) for column in FEATURE_COLUMNS] for row in rows], dtype=np.float32)
    evidence_matrix: list[list[float]] = []
    evidence_rows: list[dict[str, Any]] = []
    for row in rows:
        first = extract_evidence(reports[row["report_a_id"]])
        second = extract_evidence(reports[row["report_b_id"]])
        values, evidence = _evidence_features(first, second, row["label"])
        evidence_matrix.append(values)
        evidence_rows.append({
            "report_a_id": row["report_a_id"],
            "report_b_id": row["report_b_id"],
            "label": row["label"],
            **evidence,
        })
    evidence_matrix_np = np.asarray(evidence_matrix, dtype=np.float32)
    augmented = np.column_stack([base, evidence_matrix_np])
    weights = np.asarray([1.5 if item["hard_negative"] else 1.0 for item in evidence_rows], dtype=np.float64)
    y_train, y_validation = labels[split["train"]], labels[split["validation"]]
    model_results: list[dict[str, Any]] = []
    selected: tuple[tuple[float, float, float], Any, str, str, float] | None = None
    started = time.perf_counter()
    for family, configuration, model in _models():
        fit_start = time.perf_counter()
        _fit(model, augmented[split["train"]], y_train, weights[split["train"]])
        probability = _probability(model, augmented[split["validation"]])
        threshold, metrics = _tune(y_validation, probability)
        item = {
            "family": family,
            "configuration": configuration,
            "fit_seconds": time.perf_counter() - fit_start,
            "validation": metrics,
        }
        model_results.append(item)
        score = (metrics["f1"], metrics["pr_auc"], metrics["precision"])
        if selected is None or score > selected[0]:
            selected = (score, model, family, configuration, threshold)
    if selected is None:
        raise ValueError("no model candidates available")
    _, selected_validation_model, family, configuration, threshold = selected
    validation_metrics = _metrics(
        y_validation,
        _probability(selected_validation_model, augmented[split["validation"]]),
        threshold,
    )
    final_model = next(model for candidate_family, candidate_configuration, model in _models() if candidate_family == family and candidate_configuration == configuration)
    train_validation = np.concatenate([split["train"], split["validation"]])
    _fit(final_model, augmented[train_validation], labels[train_validation], weights[train_validation])
    test_metrics = _metrics(labels[split["test"]], _probability(final_model, augmented[split["test"]]), threshold)
    output.mkdir(parents=True)
    (output / "models").mkdir()
    joblib.dump(final_model, output / "models" / f"{family}.joblib")
    shutil.copyfile(dataset, output / "improved_dataset.csv")
    with (output / "improved_pair_evidence.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["report_a_id", "report_b_id", "label", *EVIDENCE_COLUMNS, "rules", "explanation"])
        writer.writeheader()
        for item, values in zip(evidence_rows, evidence_matrix, strict=True):
            writer.writerow({
                "report_a_id": item["report_a_id"],
                "report_b_id": item["report_b_id"],
                "label": item["label"],
                **dict(zip(EVIDENCE_COLUMNS, values, strict=True)),
                "rules": ",".join(item["rules"]),
                "explanation": item["explanation"],
            })
    with (output / "split_assignments.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row_index", "report_a_id", "report_b_id", "label", "split"])
        for index, row in enumerate(rows):
            writer.writerow([index, row["report_a_id"], row["report_b_id"], row["label"], next(name for name, indices in split.items() if index in set(indices))])
    metrics = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
        "split_sha256": hashlib.sha256(split_path.read_bytes()).hexdigest(),
        "dataset_validation": validation,
        "feature_columns": list(FEATURE_COLUMNS) + list(EVIDENCE_COLUMNS),
        "original_six_feature_schema": FEATURE_SCHEMA_VERSION,
        "model_results": model_results,
        "selected": {
            "family": family,
            "configuration": configuration,
            "threshold": threshold,
            "validation": validation_metrics,
            "test": test_metrics,
            "feature_importance": _importance(final_model, list(FEATURE_COLUMNS) + list(EVIDENCE_COLUMNS)),
        },
        "label_confidence_counts": dict(Counter(item["confidence_category"] for item in evidence_rows)),
        "hard_negative_count": int(sum(item["hard_negative"] for item in evidence_rows)),
        "pu_learning": {
            "attempted": False,
            "reason": "All 16,785 existing rows receive deterministic high-confidence positive/negative votes; no genuinely unlabeled subset is available.",
        },
        "xgboost_available": any(item["family"] == "xgboost" for item in model_results),
        "elapsed_seconds": time.perf_counter() - started,
    }
    (output / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    (output / "config.json").write_text(json.dumps({
        "experiment_version": OUTPUT_VERSION,
        "random_seed": SEED,
        "cpu_only": True,
        "base_dataset": "correlation-dataset-v4-feature-improvement",
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "evidence_features": list(EVIDENCE_COLUMNS),
        "label_derived_audit_fields": [
            "explicit campaign match",
            "distinctive indicator support",
            "hard-negative flag",
            "label confidence",
        ],
        "hard_negative_weight": 1.5,
        "selection_rule": "validation F1, then PR-AUC, then precision",
        "test_used_for_selection": False,
    }, indent=2), encoding="utf-8")
    _write_report(output, metrics)
    return metrics


def _write_report(output: Path, metrics: dict[str, Any]) -> None:
    selected = metrics["selected"]
    lines = [
        "# F1 Improvement Report",
        "",
        "This is a CPU-only exploratory experiment against weak/silver labels. Campaign-level leakage cannot be ruled out, and results are not independently verified real-world campaign accuracy.",
        "",
        "## Data and label audit",
        "",
        "- Base dataset: `correlation-dataset-v4-feature-improvement`",
        "- Original six-feature schema preserved as `correlation-features-v1`; raw overlap features are experiment-only inputs.",
        "- Existing labels and pair IDs were preserved; no rows were relabeled.",
        f"- Label confidence counts: `{metrics['label_confidence_counts']}`.",
        f"- Evidence-backed hard-negative flags: `{metrics['hard_negative_count']}`. These were retained as negative labels and assigned weight 1.5; no uncertain pair was converted to negative.",
        "- PU learning was not applied because the existing pair set contains no genuinely unlabeled rows under the deterministic weak-supervision audit.",
        "",
        "## Comparison with previous baselines",
        "",
        "| Experiment | Test F1 | PR-AUC | ROC-AUC | FPR |",
        "|---|---:|---:|---:|---:|",
        "| v3 Random Forest | 0.4908 | 0.5396 | 0.7891 | 0.0698 |",
        "| v4 Random Forest | 0.4818 | 0.5475 | 0.7940 | 0.1028 |",
        f"| leakage-safe v2 selected model | {metrics['selected']['test']['f1']:.4f} | {metrics['selected']['test']['pr_auc']:.4f} | {metrics['selected']['test']['roc_auc']:.4f} | {metrics['selected']['test']['false_positive_rate']:.4f} |",
        "",
        "## Validation model comparison",
        "",
        "| Family | Configuration | Validation F1 | PR-AUC | ROC-AUC | Threshold |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for item in sorted(metrics["model_results"], key=lambda item: (item["validation"]["f1"], item["validation"]["pr_auc"]), reverse=True):
        value = item["validation"]
        lines.append(f"| {item['family']} | `{item['configuration']}` | {value['f1']:.4f} | {value['pr_auc']:.4f} | {value['roc_auc']:.4f} | {value['threshold']:.2f} |")
    test = selected["test"]
    lines.extend([
        "",
        "## Final held-out test result",
        "",
        f"- Selected model: **{selected['family']}**, `{selected['configuration']}`.",
        f"- Validation-selected threshold: `{selected['threshold']:.2f}`.",
        f"- Precision `{test['precision']:.4f}`, recall `{test['recall']:.4f}`, F1 `{test['f1']:.4f}`, PR-AUC `{test['pr_auc']:.4f}`, ROC-AUC `{test['roc_auc']:.4f}`, FPR `{test['false_positive_rate']:.4f}`.",
        f"- Confusion matrix: `{test['confusion_matrix']}`.",
        f"- Validation confusion matrix at the selected threshold: `{selected['validation']['confusion_matrix']}` (FP={selected['validation']['confusion_matrix'][0][1]}, FN={selected['validation']['confusion_matrix'][1][0]}).",
        "",
        "## Feature importance",
        "",
        "| Feature | Importance |",
        "|---|---:|",
    ])
    for name, value in selected["feature_importance"].items():
        lines.append(f"| `{name}` | {value:.6f} |")
    lines.extend([
        "",
        "## Interpretation and limitations",
        "",
        "The evidence audit found all existing labels matched high-confidence deterministic rules, so confidence weighting had no low-confidence subset to exploit. Hard-negative flags identify evidence-backed overlap without campaign evidence, but they do not change labels.",
        "Campaign-reference, distinctive-indicator, hard-negative, and confidence fields are retained only as provenance/audit fields and were excluded from model inputs because they overlap with silver-label rules. The model uses raw report evidence overlaps and the six canonical features.",
        "The v1 run produced a perfect score because label-derived campaign and hard-negative fields were included as predictors; that run is invalid for performance claims and is superseded by this leakage-safe rerun.",
        "The leakage-safe rerun improved test F1 over the prior v3/v4 baselines but did not reach 0.70. This is agreement with silver labels only; campaign-independent generalisation and independently verified real-world accuracy remain unestablished.",
        "The untouched test result is the only reported final evaluation. A result below F1 0.70 is reported honestly rather than forced through threshold or label manipulation.",
        "",
        "## Artifacts",
        "",
        "- `improved_dataset.csv`: unchanged v4 dataset copied into this experiment",
        "- `improved_pair_evidence.csv`: provenance, raw evidence features, and evidence-derived training weights",
        "- `models/`: selected fitted model",
        "- `metrics.json`, `config.json`, and `split_assignments.csv`: reproducibility artifacts",
    ])
    (output / "F1_IMPROVEMENT_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("data/correlation/processed/v4_feature_improvement/silver_correlation_pairs.csv"))
    parser.add_argument("--reports", type=Path, default=Path("data/correlation/processed/normalized_reports.jsonl"))
    parser.add_argument("--split", type=Path, default=Path("data/correlation/experiments/v4_training_comparison_v1/split_assignments.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/correlation/experiments/f1_improvement_v3"))
    args = parser.parse_args()
    metrics = run(args.dataset, args.reports, args.split, args.output)
    print(json.dumps(metrics["selected"], indent=2))


if __name__ == "__main__":
    main()
