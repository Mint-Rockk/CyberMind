from collections.abc import Mapping, Sequence
from typing import Any

from app.correlation.feature_schema import FEATURE_NAMES, FEATURE_SCHEMA_VERSION, FeatureVector


def validate_feature_vector(
    values: Sequence[float],
    *,
    schema_version: str = FEATURE_SCHEMA_VERSION,
    evidence: Mapping[str, Any] | None = None,
) -> FeatureVector:
    """Validate an ordered six-value vector before model-adapter handoff."""
    if schema_version != FEATURE_SCHEMA_VERSION:
        raise ValueError(f"unsupported feature schema version: {schema_version}")
    if len(values) != len(FEATURE_NAMES):
        raise ValueError("feature vector must contain exactly six values")
    normalized = tuple(float(value) for value in values)
    if any(not 0.0 <= value <= 1.0 for value in normalized):
        raise ValueError("feature vector values must be between 0 and 1")
    return FeatureVector(
        values=normalized,
        evidence={name: dict(evidence.get(name, {})) if evidence else {} for name in FEATURE_NAMES},
        schema_version=schema_version,
    )
