from dataclasses import dataclass
from typing import Any

FEATURE_SCHEMA_VERSION = "correlation-features-v1"
FEATURE_NAMES = (
    "temporal_similarity",
    "entity_relationship_similarity",
    "behavioural_similarity",
    "attack_technique_similarity",
    "semantic_embedding_similarity",
    "knowledge_graph_relationship_similarity",
)
FEATURE_TYPES = {name: "float32" for name in FEATURE_NAMES}
MISSING_VALUE_POLICY = {
    "per_feature": "Return score 0.5 with available=false and a missing reason.",
    "model_vector": "Materialize missing features as neutral 0.5; preserve availability/evidence outside the six inputs.",
    "training": "Apply the same neutral 0.5 rule and retain the availability metadata for evaluation.",
}


@dataclass(frozen=True)
class FeatureVector:
    values: tuple[float, ...]
    evidence: dict[str, dict[str, Any]]
    schema_version: str = FEATURE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if len(self.values) != len(FEATURE_NAMES):
            raise ValueError("feature vector must contain exactly six values")
        if any(not 0.0 <= value <= 1.0 for value in self.values):
            raise ValueError("feature vector values must be between 0 and 1")
        if set(self.evidence) != set(FEATURE_NAMES):
            raise ValueError("feature evidence must cover exactly the six schema features")

    def as_model_input(self) -> tuple[float, ...]:
        """Return the only six values allowed as model inputs, in schema order."""
        return self.values


def validate_feature_result(feature_name: str, score: float) -> None:
    if feature_name not in FEATURE_NAMES:
        raise ValueError(f"unknown correlation feature: {feature_name}")
    if not isinstance(score, (float, int)) or not 0.0 <= float(score) <= 1.0:
        raise ValueError("correlation feature scores must be numeric values between 0 and 1")
