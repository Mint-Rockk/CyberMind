from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Any, Mapping

from app.ml.correlation.feature_schema import FeatureInput


class PredictorUnavailableError(RuntimeError):
    """Raised when the configured predictor cannot be made available."""


class CorrelationPredictor(ABC):
    """Common contract implemented by baseline and externally trained predictors."""

    @abstractmethod
    def predict_probability(self, features: FeatureInput) -> float:
        raise NotImplementedError

    def predict_batch(self, feature_vectors: Sequence[FeatureInput]) -> list[float]:
        return [self.predict_probability(features) for features in feature_vectors]

    def predict_pair(
        self,
        features: FeatureInput,
        first_report: Mapping[str, Any],
        second_report: Mapping[str, Any],
    ) -> tuple[float, dict[str, Any]]:
        return self.predict_probability(features), {}

    def predict_pairs(
        self,
        items: Sequence[tuple[FeatureInput, Mapping[str, Any], Mapping[str, Any]]],
    ) -> list[tuple[float, dict[str, Any]]]:
        return [self.predict_pair(feat, first, second) for feat, first, second in items]

    @abstractmethod
    def get_model_metadata(self) -> dict[str, Any]:
        raise NotImplementedError
