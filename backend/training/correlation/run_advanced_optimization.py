"""Run validation-only CPU model optimisation on the preserved v3 pair split."""

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
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, confusion_matrix, f1_score, precision_score, recall_score, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.correlation.feature_schema import FEATURE_NAMES, FEATURE_SCHEMA_VERSION
from training.correlation.run_exploratory_training import FEATURE_COLUMNS, SEED, _read_rows, _validate_dataset

OUTPUT_VERSION = "advanced-model-optimization-v2"
THRESHOLDS = tuple(round(value, 2) for value in np.linspace(0.10, 0.90, 17))
POSITIVE_WEIGHT = 14519 / 2266


def _probabilities(model: Any, values: np.ndarray) -> np.ndarray:
    return np.asarray(model.predict_proba(values)[:, 1], dtype=float)


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
        "positive_predictions": int(predictions.sum()),
    }


def _tune(y_true: np.ndarray, probabilities: np.ndarray) -> tuple[float, dict[str, Any]]:
    candidates = [(threshold, _metrics(y_true, probabilities, threshold)) for threshold in THRESHOLDS]
    return max(candidates, key=lambda item: (item[1]["f1"], item[1]["pr_auc"], item[1]["precision"], -item[0]))


def _load_split(path: Path, row_count: int) -> dict[str, np.ndarray]:
    assignments: dict[str, list[int]] = {"train": [], "validation": [], "test": []}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            index = int(row["row_index"])
            if not 0 <= index < row_count:
                raise ValueError(f"split row index out of range: {index}")
            assignments[row["split"]].append(index)
    if any(not values for values in assignments.values()):
        raise ValueError("saved split is missing a partition")
    all_indices = [index for values in assignments.values() for index in values]
    if len(set(all_indices)) != row_count or len(all_indices) != row_count:
        raise ValueError("saved split is not a complete disjoint partition")
    return {name: np.asarray(values, dtype=int) for name, values in assignments.items()}


def _missing_indicators(values: np.ndarray) -> np.ndarray:
    # The v3 metadata records neutral 0.5 materialization for these features.
    columns = (0, 2, 3)
    return np.column_stack([np.isclose(values[:, index], 0.5, atol=1e-8) for index in columns]).astype(np.float32)


def _feature_matrix(values: np.ndarray, variant: str) -> np.ndarray:
    if variant == "all_features":
        return values
    if variant.startswith("ablation_without_"):
        name = variant.removeprefix("ablation_without_")
        index = FEATURE_COLUMNS.index(name)
        return np.delete(values, index, axis=1)
    if variant == "all_features_with_missing_indicators":
        return np.column_stack([values, _missing_indicators(values)])
    raise ValueError(f"unknown feature variant: {variant}")


def _candidates() -> list[tuple[str, str, Any]]:
    candidates: list[tuple[str, str, Any]] = []
    for c in (0.1, 1.0, 10.0, 100.0):
        candidates.append((
            "logistic_regression", f"C_{c}",
            Pipeline([
                ("scaler", StandardScaler()),
                ("classifier", LogisticRegression(C=c, class_weight="balanced", max_iter=3000, random_state=SEED)),
            ]),
        ))
    for depth, leaf, features in ((None, 1, "sqrt"), (None, 2, "sqrt"), (16, 1, "sqrt"), (None, 1, 1.0)):
        candidates.append((
            "random_forest", f"depth_{depth}_leaf_{leaf}_features_{features}",
            RandomForestClassifier(
                n_estimators=500, max_depth=depth, min_samples_leaf=leaf, max_features=features,
                class_weight="balanced_subsample", n_jobs=-1, random_state=SEED,
            ),
        ))
    for depth, leaf in ((None, 1), (None, 2), (16, 1), (16, 2)):
        candidates.append((
            "extra_trees", f"depth_{depth}_leaf_{leaf}",
            ExtraTreesClassifier(
                n_estimators=500, max_depth=depth, min_samples_leaf=leaf, class_weight="balanced",
                n_jobs=-1, random_state=SEED,
            ),
        ))
    for learning_rate, max_leaf_nodes, l2 in ((0.05, 15, 1.0), (0.05, 31, 1.0), (0.1, 15, 1.0), (0.05, 31, 5.0)):
        candidates.append((
            "hist_gradient_boosting", f"lr_{learning_rate}_leaves_{max_leaf_nodes}_l2_{l2}",
            HistGradientBoostingClassifier(
                learning_rate=learning_rate, max_leaf_nodes=max_leaf_nodes, l2_regularization=l2,
                max_iter=300, random_state=SEED,
            ),
        ))
    try:
        from xgboost import XGBClassifier
    except ImportError:
        return candidates
    for depth, learning_rate, child_weight in ((3, 0.05, 1), (5, 0.05, 1), (3, 0.1, 3)):
        candidates.append((
            "xgboost", f"depth_{depth}_eta_{learning_rate}_child_{child_weight}",
            XGBClassifier(
                objective="binary:logistic", eval_metric="logloss", tree_method="hist", device="cpu",
                max_depth=depth, learning_rate=learning_rate, min_child_weight=child_weight,
                n_estimators=400, subsample=0.9, colsample_bytree=0.9,
                scale_pos_weight=POSITIVE_WEIGHT, random_state=SEED, n_jobs=-1,
            ),
        ))
    return candidates


def _fit(model: Any, x: np.ndarray, y: np.ndarray) -> Any:
    if isinstance(model, HistGradientBoostingClassifier):
        model.fit(x, y, sample_weight=np.where(y == 1, POSITIVE_WEIGHT, 1.0))
    else:
        model.fit(x, y)
    return model


def _write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding="utf-8")


def _feature_importance(model: Any, feature_names: list[str]) -> dict[str, float]:
    estimator = model.named_steps["classifier"] if isinstance(model, Pipeline) else model
    if hasattr(estimator, "feature_importances_"):
        values = np.asarray(estimator.feature_importances_, dtype=float)
    elif hasattr(estimator, "coef_"):
        values = np.abs(np.asarray(estimator.coef_[0], dtype=float))
    else:
        return {}
    return {
        name: float(value)
        for name, value in sorted(
            zip(feature_names, values), key=lambda item: item[1], reverse=True
        )
    }


def run(dataset_path: Path, split_path: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError(f"experiment directory already exists: {output}")
    rows = _read_rows(dataset_path)
    dataset = _validate_dataset(rows, dataset_path)
    split = _load_split(split_path, len(rows))
    values = np.asarray([[float(row[column]) for column in FEATURE_COLUMNS] for row in rows], dtype=np.float32)
    labels = np.asarray([1 if row["label"] == "positive" else 0 for row in rows], dtype=np.int8)
    source_hash = hashlib.sha256(dataset_path.read_bytes()).hexdigest()
    if source_hash != "72ac59730e14eaa8307434b3f81c2aff19e963eaa15458e7696695e1d69e7749":
        raise ValueError("dataset hash differs from the preserved exploratory training input")
    output.mkdir(parents=True)
    (output / "models").mkdir()
    train, validation, test = (split[name] for name in ("train", "validation", "test"))
    y_train, y_validation = labels[train], labels[validation]
    validation_results: list[dict[str, Any]] = []
    fitted: dict[str, tuple[Any, str, str, float]] = {}
    started = time.perf_counter()
    for variant in ("all_features", "all_features_with_missing_indicators"):
        x_train = _feature_matrix(values[train], variant)
        x_validation = _feature_matrix(values[validation], variant)
        for family, configuration, model in _candidates():
            fit_started = time.perf_counter()
            _fit(model, x_train, y_train)
            probabilities = _probabilities(model, x_validation)
            threshold, metrics = _tune(y_validation, probabilities)
            validation_results.append({
                "family": family, "configuration": configuration, "feature_variant": variant,
                "fit_seconds": time.perf_counter() - fit_started, "validation": metrics,
            })
            key = (metrics["f1"], metrics["pr_auc"], metrics["precision"])
            current = fitted.get("best")
            if current is None or key > current[3]:
                fitted["best"] = (model, family, variant, key, configuration, threshold)
    best_model, best_family, best_variant, _, best_configuration, best_threshold = fitted["best"]

    # Feature ablations use a fixed, validation-selected family/configuration and do not inspect test rows.
    ablations: list[dict[str, Any]] = []
    for removed in FEATURE_COLUMNS:
        variant = f"ablation_without_{removed}"
        model = next(model for family, configuration, model in _candidates()
                     if family == best_family and configuration == best_configuration)
        _fit(model, _feature_matrix(values[train], variant), y_train)
        probability = _probabilities(model, _feature_matrix(values[validation], variant))
        threshold, metrics = _tune(y_validation, probability)
        ablations.append({"removed_feature": removed, "validation": metrics, "threshold": threshold})

    # Refit only the selected configuration on train+validation, then evaluate test once.
    train_validation = np.concatenate([train, validation])
    final_model = next(model for family, configuration, model in _candidates()
                       if family == best_family and configuration == best_configuration)
    _fit(final_model, _feature_matrix(values[train_validation], best_variant), labels[train_validation])
    test_probability = _probabilities(final_model, _feature_matrix(values[test], best_variant))
    test_metrics = _metrics(labels[test], test_probability, best_threshold)
    selected_feature_names = list(FEATURE_NAMES)
    if best_variant == "all_features_with_missing_indicators":
        selected_feature_names.extend(
            [
                "temporal_missing_indicator",
                "behavioural_missing_indicator",
                "attack_technique_missing_indicator",
            ]
        )
    correlations = np.corrcoef(values[train].T)
    training_correlations = {
        FEATURE_COLUMNS[row]: {
            FEATURE_COLUMNS[column]: float(correlations[row, column])
            for column in range(len(FEATURE_COLUMNS))
        }
        for row in range(len(FEATURE_COLUMNS))
    }
    joblib.dump(final_model, output / "models" / f"{best_family}.joblib")
    _write_json(output / "preprocessing.json", {
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "feature_variant": best_variant,
        "feature_columns": list(FEATURE_NAMES),
        "missing_indicator_source": "neutral 0.5 for temporal, behavioural, and ATT&CK features per v3 metadata",
        "class_imbalance": "balanced class weights or positive sample weight",
        "test_threshold": best_threshold,
    })
    _write_json(output / "config.json", {
        "experiment_version": OUTPUT_VERSION, "dataset": "correlation-dataset-v3",
        "dataset_sha256": source_hash, "split_source": str(split_path),
        "split_sha256": hashlib.sha256(split_path.read_bytes()).hexdigest(),
        "feature_schema_version": FEATURE_SCHEMA_VERSION, "random_seed": SEED,
        "cpu_only": True, "campaign_grouping_available": False,
        "selection_rule": "validation F1, then PR-AUC, then precision",
        "xgboost_available": any(item["family"] == "xgboost" for item in validation_results),
        "training_rows": int(len(train_validation)), "test_rows": int(len(test)),
    })
    with (output / "split_assignments.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["row_index", "split", "label"])
        for name, indices in split.items():
            for index in indices:
                writer.writerow([int(index), name, rows[index]["label"]])
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset": dataset,
        "split_counts": {name: {"rows": int(len(indices)), "positive": int(labels[indices].sum()), "negative": int(len(indices) - labels[indices].sum())} for name, indices in split.items()},
        "elapsed_seconds": time.perf_counter() - started,
        "tested_configurations": validation_results,
        "feature_ablation_validation": ablations,
        "training_feature_correlations": training_correlations,
        "selected_feature_importance": _feature_importance(
            final_model, selected_feature_names
        ),
        "selected": {"family": best_family, "configuration": best_configuration, "feature_variant": best_variant, "validation_threshold": best_threshold, "test": test_metrics},
        "original_random_forest_test": {"f1": 0.4793388429752066, "pr_auc": 0.5330278569237061, "roc_auc": 0.7884013936152974},
        "target_f1": 0.70, "target_achieved": test_metrics["f1"] >= 0.70,
        "calibration": {"applied": False, "reason": "No calibration method was justified from the fixed validation split; raw probabilities were threshold-tuned on validation only."},
    }
    _write_json(output / "metrics.json", result)
    _write_report(output, result)
    return result


def _write_report(output: Path, result: dict[str, Any]) -> None:
    selected = result["selected"]
    lines = [
        "# Advanced Model Optimization Report", "",
        "## Scope and evaluation integrity", "",
        "This is a CPU-only exploratory optimization against weak/silver labels. The original v3 dataset, labels, pair IDs, six feature values, exploratory split, and exploratory artifacts were not modified.",
        "Campaign-level leakage cannot be ruled out because campaign/incident grouping was infeasible; metrics may be optimistic and are not campaign-independent or independently verified real-world accuracy.",
        "",
        "## Configuration", "",
        f"- Dataset: `correlation-dataset-v3` (`{result['dataset']['source_sha256']}`)",
        f"- Schema: `{FEATURE_SCHEMA_VERSION}`",
        f"- Seed: `{SEED}`; split: preserved stratified pair-level 70:15:15",
        "- CPU-only: yes; test set was not used for model or threshold selection",
        f"- Missingness: v3 neutral `0.5` policy preserved; optional indicators only identify documented neutral materialization",
        "",
        "## Counts", "",
        "| Split | Rows | Negative | Positive |", "|---|---:|---:|---:|",
    ]
    for name in ("train", "validation", "test"):
        item = result["split_counts"][name]
        lines.append(f"| {name} | {item['rows']} | {item['negative']} | {item['positive']} |")
    lines.extend(["", "## Validation model/configuration comparison", "", "| Family | Configuration | Feature variant | F1 | PR-AUC | ROC-AUC | Threshold |", "|---|---|---|---:|---:|---:|---:|"])
    for item in sorted(result["tested_configurations"], key=lambda x: (x["validation"]["f1"], x["validation"]["pr_auc"]), reverse=True):
        metrics = item["validation"]
        lines.append(f"| {item['family']} | `{item['configuration']}` | `{item['feature_variant']}` | {metrics['f1']:.4f} | {metrics['pr_auc']:.4f} | {metrics['roc_auc']:.4f} | {metrics['threshold']:.2f} |")
    lines.extend(["", "## Selected model and unchanged test evaluation", "", f"- Selected by validation F1/PR-AUC/precision: **{selected['family']}**, `{selected['configuration']}`, `{selected['feature_variant']}`.", f"- Validation threshold: `{selected['validation_threshold']:.2f}`.", "", "| Precision | Recall | F1 | PR-AUC | ROC-AUC | FPR |", "|---:|---:|---:|---:|---:|---:|"])
    test = selected["test"]
    lines.append(f"| {test['precision']:.4f} | {test['recall']:.4f} | {test['f1']:.4f} | {test['pr_auc']:.4f} | {test['roc_auc']:.4f} | {test['false_positive_rate']:.4f} |")
    lines.extend([f"- Confusion matrix: `{test['confusion_matrix']}`.", f"- Original Random Forest F1: `{result['original_random_forest_test']['f1']:.4f}`; optimized test F1: `{test['f1']:.4f}`.", f"- Target F1 >= 0.70 achieved: **{result['target_achieved']}**.", "", "## Selected-model feature importance", "", "| Feature | Importance |", "|---|---:|"])
    for name, importance in result["selected_feature_importance"].items():
        lines.append(f"| `{name}` | {importance:.6f} |")
    lines.extend(["", "## Training feature correlations", "", "Correlations were calculated on training rows only.", "", "| Feature | Most correlated feature | Absolute correlation |", "|---|---|---:|"])
    for name, correlations in result["training_feature_correlations"].items():
        peers = [(peer, value) for peer, value in correlations.items() if peer != name]
        peer, value = max(peers, key=lambda item: abs(item[1]))
        lines.append(f"| `{name}` | `{peer}` | {abs(value):.4f} |")
    lines.extend(["", "## Feature ablations (validation only)", "", "| Removed feature | F1 | PR-AUC | Threshold |", "|---|---:|---:|---:|"])
    for item in result["feature_ablation_validation"]:
        metrics = item["validation"]
        lines.append(f"| `{item['removed_feature']}` | {metrics['f1']:.4f} | {metrics['pr_auc']:.4f} | {item['threshold']:.2f} |")
    lines.extend(["", "## Calibration, redundancy, and limitations", "", "- No probability calibration was applied: the fixed validation data supported threshold tuning, but did not justify adding a calibration stage without an independent calibration set.", "- Feature redundancy was investigated through six ablations and the documented neutral-value indicators; no source feature values were altered.", "- This experiment does not establish real-world campaign-correlation accuracy or campaign-independent generalisation.", "", "## Artifacts", "", "- `models/`: selected fitted model", "- `metrics.json`: all validation configurations, ablations, and one selected-model test evaluation", "- `split_assignments.csv`, `config.json`, and `preprocessing.json`: reproducibility metadata"])
    (output / "ADVANCED_MODEL_OPTIMIZATION_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=Path("data/correlation/processed/v3/silver_correlation_pairs.csv"))
    parser.add_argument("--split", type=Path, default=Path("data/correlation/experiments/exploratory_pair_v1/split_assignments.csv"))
    parser.add_argument("--output", type=Path, default=Path("data/correlation/experiments/advanced_model_optimization_v2"))
    args = parser.parse_args()
    result = run(args.dataset, args.split, args.output)
    print(json.dumps(result["selected"], indent=2))


if __name__ == "__main__":
    main()
