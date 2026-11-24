import math
from collections.abc import Mapping, Sequence
from typing import Any

from app.ml.correlation.base import CorrelationPredictor
from app.ml.correlation.feature_schema import (
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    PREPROCESSING_VERSION,
    FeatureInput,
    coerce_feature_input,
    validate_feature_schema,
)

_REQUIRED_METADATA = {
    "model_name",
    "model_version",
    "training_date",
    "feature_names",
    "feature_schema_version",
    "preprocessing_version",
    "training_dataset_reference",
    "evaluation_metrics",
    "artifact_location",
}


class TrainedModelAdapter(CorrelationPredictor):
    """Adapter for a trusted external model exposing scikit-learn-style predict_proba."""

    def __init__(self, model: Any, metadata: Mapping[str, Any]) -> None:
        if not callable(getattr(model, "predict_proba", None)):
            raise ValueError("trained artifact must expose predict_proba")
        missing = _REQUIRED_METADATA - set(metadata)
        if missing:
            raise ValueError(f"trained model metadata is missing: {sorted(missing)}")
        validate_feature_schema(
            metadata["feature_names"],
            metadata["feature_schema_version"],
            metadata["preprocessing_version"],
        )
        if not isinstance(metadata["evaluation_metrics"], Mapping):
            raise ValueError("evaluation_metrics must be a JSON object")
        self.model = model
        self.metadata = dict(metadata)

    def predict_probability(self, features: FeatureInput) -> float:
        values = coerce_feature_input(features)
        try:
            probabilities = self.model.predict_proba([values])
            probability = _positive_probability(probabilities)
        except ValueError:
            raise
        except (TypeError, ValueError, AttributeError, IndexError, RuntimeError) as exc:
            raise RuntimeError("trained model prediction failed") from exc
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            raise ValueError("trained model returned a probability outside [0, 1]")
        return probability

    def predict_batch(self, feature_vectors: Sequence[FeatureInput]) -> list[float]:
        values = [coerce_feature_input(features) for features in feature_vectors]
        if not values:
            return []
        try:
            probabilities = self.model.predict_proba(values)
            return [_validate_probability(_positive_probability(row)) for row in probabilities]
        except ValueError:
            raise
        except (TypeError, ValueError, AttributeError, IndexError, RuntimeError) as exc:
            raise RuntimeError("trained model batch prediction failed") from exc

    def get_model_metadata(self) -> dict[str, Any]:
        return {
            **self.metadata,
            "feature_names": list(FEATURE_NAMES),
            "feature_schema_version": FEATURE_SCHEMA_VERSION,
            "preprocessing_version": PREPROCESSING_VERSION,
            "is_trained_model": True,
        }


def _positive_probability(probabilities: Any) -> float:
    rows = list(probabilities)
    first = rows[0] if rows else None
    if isinstance(first, (list, tuple)) or (
        first is not None and hasattr(first, "shape") and len(first.shape) > 0
    ):
        row = list(rows[0])
    else:
        row = rows
    if not row:
        raise ValueError("trained model returned no probabilities")
    if len(row) == 1:
        return _validate_probability(float(row[0]))
    return _validate_probability(float(row[1]))


def _validate_probability(value: float) -> float:
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("trained model returned a probability outside [0, 1]")
    return value
