from typing import Any

from app.correlation.types import FeatureResult
from app.correlation.utils import representation, set_similarity


def entity_relationship_similarity(first: Any, second: Any) -> FeatureResult:
    left = representation(first).entities
    right = representation(second).entities
    score, evidence = set_similarity(left, right)
    return FeatureResult("entity_relationship_similarity", 0.5 if score is None else score, score is not None, evidence)
