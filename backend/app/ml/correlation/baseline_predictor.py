from collections.abc import Mapping
from typing import Any

from app.ml.correlation.base import CorrelationPredictor
from app.ml.correlation.feature_schema import FEATURE_NAMES, FeatureInput, coerce_feature_input

DEFAULT_WEIGHTS = {name: 1.0 / len(FEATURE_NAMES) for name in FEATURE_NAMES}


class BaselinePredictor(CorrelationPredictor):
    """Transparent weighted heuristic; this is not a trained machine-learning model."""

    def __init__(
        self,
        weights: Mapping[str, float] | None = None,
        version: str = "baseline-heuristic-v1",
    ) -> None:
        configured = dict(DEFAULT_WEIGHTS if weights is None else weights)
        if set(configured) != set(FEATURE_NAMES):
            raise ValueError("baseline weights must cover exactly the six feature names")
        if any(value < 0 for value in configured.values()):
            raise ValueError("baseline weights cannot be negative")
        total = sum(configured.values())
        if total <= 0:
            raise ValueError("baseline weights must have a positive sum")
        self.weights = {name: configured[name] / total for name in FEATURE_NAMES}
        self.version = version

    def predict_probability(self, features: FeatureInput) -> float:
        values = coerce_feature_input(features)
        return sum(weight * value for weight, value in zip(self.weights.values(), values, strict=True))

    def get_model_metadata(self) -> dict[str, Any]:
        return {
            "model_type": "baseline_heuristic",
            "model_name": "Weighted six-feature baseline",
            "model_version": self.version,
            "feature_names": list(FEATURE_NAMES),
            "feature_schema_version": "correlation-features-v1",
            "weights": dict(self.weights),
            "is_trained_model": False,
        }
