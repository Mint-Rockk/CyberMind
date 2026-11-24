from collections.abc import Mapping, Sequence
from typing import TypeAlias

from app.correlation.feature_schema import (
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    FEATURE_TYPES,
    FeatureVector,
)

PREPROCESSING_VERSION = "neutral-missing-v1"
FeatureInput: TypeAlias = FeatureVector | Mapping[str, float] | Sequence[float]


def coerce_feature_input(features: FeatureInput) -> tuple[float, ...]:
    """Convert only the approved six-feature representations into schema order."""
    if isinstance(features, FeatureVector):
        if features.schema_version != FEATURE_SCHEMA_VERSION:
            raise ValueError(f"unsupported feature schema version: {features.schema_version}")
        values = features.as_model_input()
    elif isinstance(features, Mapping):
        if set(features) != set(FEATURE_NAMES):
            raise ValueError("feature mapping must contain exactly the six approved feature names")
        values = tuple(features[name] for name in FEATURE_NAMES)
    else:
        values = tuple(features)
    if len(values) != len(FEATURE_NAMES):
        raise ValueError("model input must contain exactly six features")
    normalized = tuple(float(value) for value in values)
    if any(not 0.0 <= value <= 1.0 for value in normalized):
        raise ValueError("model input features must be between 0 and 1")
    return normalized


def validate_feature_schema(
    feature_names: Sequence[str],
    schema_version: str,
    preprocessing_version: str,
) -> None:
    if tuple(feature_names) != FEATURE_NAMES:
        raise ValueError("trained artifact feature names/order do not match the six-feature schema")
    if schema_version != FEATURE_SCHEMA_VERSION:
        raise ValueError(f"trained artifact uses unsupported feature schema version: {schema_version}")
    if preprocessing_version != PREPROCESSING_VERSION:
        raise ValueError(
            f"trained artifact uses unsupported preprocessing version: {preprocessing_version}"
        )
