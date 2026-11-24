import math
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from app.correlation.feature_schema import FEATURE_NAMES, FeatureVector
from app.ml.correlation.base import CorrelationPredictor, PredictorUnavailableError
from app.ml.correlation.model_loader import load_model_artifact, load_model_metadata

EVIDENCE_FEATURE_NAMES = (
    "shared_actor",
    "shared_malware",
    "shared_tool",
    "shared_technique",
    "shared_indicator",
    "cross_vendor",
)
MODEL_FEATURE_NAMES = (
    "temporal_similarity",
    "entity_relationship_similarity",
    "behavioural_similarity",
    "attack_technique_similarity",
    "semantic_similarity",
    "knowledge_graph_similarity",
    *EVIDENCE_FEATURE_NAMES,
)


def _report_evidence(report: Mapping[str, Any]) -> Any:
    from training.correlation.weak_supervision import extract_evidence

    return extract_evidence(dict(report))


def build_evidence_features(
    first_report: Mapping[str, Any],
    second_report: Mapping[str, Any],
) -> tuple[dict[str, float], dict[str, Any]]:
    first = _report_evidence(first_report)
    second = _report_evidence(second_report)
    shared = {
        "shared_actor": sorted(set(first.actor_names) & set(second.actor_names)),
        "shared_malware": sorted(set(first.malware_names) & set(second.malware_names)),
        "shared_tool": sorted(set(first.tool_names) & set(second.tool_names)),
        "shared_technique": sorted(set(first.technique_names) & set(second.technique_names)),
        "shared_indicator": sorted(
            {item.value for item in first.distinctive_refs}
            & {item.value for item in second.distinctive_refs}
        ),
    }
    values = {
        name: float(bool(items))
        for name, items in shared.items()
    }
    values["cross_vendor"] = float(first.source_vendor != second.source_vendor)
    return values, {
        "status": "available",
        "features": values,
        "shared_values": shared,
        "method": "weak_supervision.extract_evidence.raw_overlap_v1",
        "source_reports": [first.report_id, second.report_id],
    }


class EvidenceAwareRandomForestPredictor(CorrelationPredictor):
    """Inference adapter for the f1-improvement-v3 Random Forest artifact."""

    def __init__(
        self,
        model: Any,
        metadata: Mapping[str, Any],
        threshold: float,
    ) -> None:
        if not callable(getattr(model, "predict_proba", None)):
            raise ValueError("evidence-aware artifact must expose predict_proba")
        feature_names = tuple(metadata.get("feature_columns", ()))
        if feature_names != MODEL_FEATURE_NAMES:
            raise ValueError("evidence-aware artifact feature order does not match f1-improvement-v3")
        model_input_count = getattr(model, "n_features_in_", len(MODEL_FEATURE_NAMES))
        if model_input_count != len(MODEL_FEATURE_NAMES):
            raise ValueError(
                f"evidence-aware artifact expects {model_input_count} inputs; "
                f"{len(MODEL_FEATURE_NAMES)} are configured"
            )
        if metadata.get("feature_schema_version") != "correlation-features-v1":
            raise ValueError("evidence-aware artifact uses an unsupported feature schema")
        if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
            raise ValueError("evidence-aware threshold must be between 0 and 1")
        self.model = model
        self.metadata = dict(metadata)
        self.threshold = threshold

    @classmethod
    def from_paths(cls, artifact_path: Path, config_path: Path, metrics_path: Path) -> "EvidenceAwareRandomForestPredictor":
        if not artifact_path.is_file():
            raise PredictorUnavailableError(f"evidence-aware model artifact not found: {artifact_path}")
        config = load_model_metadata(config_path)
        metrics = load_model_metadata(metrics_path)
        try:
            experiment_version = config["experiment_version"]
            feature_schema_version = config["feature_schema_version"]
            training_dataset_reference = config["base_dataset"]
            selected = metrics["selected"]
            threshold = float(selected["threshold"])
            if selected["family"] != "random_forest":
                raise ValueError("selected experiment model is not Random Forest")
            feature_columns = metrics["feature_columns"]
            evaluation_metrics = selected["test"]
            if not isinstance(feature_columns, list):
                raise TypeError("experiment feature columns must be a list")
        except (KeyError, TypeError, ValueError) as exc:
            raise PredictorUnavailableError(
                f"evidence-aware experiment metadata or metrics are invalid: {exc}"
            ) from exc
        metadata = {
            "model_type": "evidence_aware_random_forest",
            "model_name": "CyberMind evidence-aware Random Forest",
            "model_version": experiment_version,
            "feature_columns": list(feature_columns),
            "input_count": len(feature_columns),
            "feature_schema_version": feature_schema_version,
            "training_dataset_reference": training_dataset_reference,
            "evaluation_metrics": evaluation_metrics,
            "artifact_location": str(artifact_path),
            "experiment_config": config,
            "is_trained_model": True,
            "threshold": threshold,
        }
        try:
            return cls(load_model_artifact(artifact_path), metadata, threshold)
        except ValueError as exc:
            raise PredictorUnavailableError(
                f"evidence-aware model is incompatible with its metadata: {exc}"
            ) from exc

    def predict_pair(
        self,
        features: FeatureVector,
        first_report: Mapping[str, Any],
        second_report: Mapping[str, Any],
    ) -> tuple[float, dict[str, Any]]:
        return self.predict_pairs([(features, first_report, second_report)])[0]

    def predict_pairs(
        self,
        items: Sequence[tuple[FeatureVector, Mapping[str, Any], Mapping[str, Any]]],
    ) -> list[tuple[float, dict[str, Any]]]:
        if not items:
            return []
        all_values: list[tuple[float, ...]] = []
        all_evidence: list[dict[str, Any]] = []
        for features, first_report, second_report in items:
            evidence_values, evidence = build_evidence_features(first_report, second_report)
            canonical = dict(zip(FEATURE_NAMES, features.values, strict=True))
            values = (
                canonical["temporal_similarity"],
                canonical["entity_relationship_similarity"],
                canonical["behavioural_similarity"],
                canonical["attack_technique_similarity"],
                canonical["semantic_embedding_similarity"],
                canonical["knowledge_graph_relationship_similarity"],
                *(evidence_values[name] for name in EVIDENCE_FEATURE_NAMES),
            )
            all_values.append(values)
            all_evidence.append(evidence)

        try:
            raw_probs = self.model.predict_proba(all_values)
            probabilities = [float(row[1]) for row in raw_probs]
        except (TypeError, ValueError, AttributeError, IndexError, RuntimeError) as exc:
            raise RuntimeError("evidence-aware model prediction failed") from exc

        results: list[tuple[float, dict[str, Any]]] = []
        for prob, values, evidence in zip(probabilities, all_values, all_evidence, strict=True):
            probability = float(prob)
            if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
                raise ValueError("evidence-aware model returned a probability outside [0, 1]")
            results.append((
                probability,
                {
                    **evidence,
                    "model_feature_order": list(MODEL_FEATURE_NAMES),
                    "model_features": dict(zip(MODEL_FEATURE_NAMES, values, strict=True)),
                },
            ))
        return results

    def predict_probability(self, features: Any) -> float:
        raise ValueError("evidence-aware predictor requires two report representations")

    def get_model_metadata(self) -> dict[str, Any]:
        return {
            **self.metadata,
            "feature_names": list(FEATURE_NAMES),
            "evidence_feature_names": list(EVIDENCE_FEATURE_NAMES),
            "threshold": self.threshold,
        }
