from typing import Any

from app.correlation.types import FeatureResult
from app.correlation.utils import representation, set_similarity


def attack_technique_similarity(first: Any, second: Any) -> FeatureResult:
    score, evidence = set_similarity(
        representation(first).attack_techniques, representation(second).attack_techniques
    )
    return FeatureResult("attack_technique_similarity", 0.5 if score is None else score, score is not None, evidence)
