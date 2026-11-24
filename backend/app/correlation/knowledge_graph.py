from typing import Any

from app.correlation.types import FeatureResult
from app.correlation.utils import representation, set_similarity


def knowledge_graph_relationship_similarity(first: Any, second: Any) -> FeatureResult:
    left = representation(first)
    right = representation(second)
    left_available = (left.metadata or {}).get("knowledge_graph_available")
    right_available = (right.metadata or {}).get("knowledge_graph_available")
    if left_available is False or right_available is False:
        return FeatureResult(
            "knowledge_graph_relationship_similarity",
            0.5,
            False,
            {"status": "missing", "reason": "one or both graph lookups were unavailable"},
        )
    if left_available is True and right_available is True:
        left_values = set(left.knowledge_graph_relationships)
        right_values = set(right.knowledge_graph_relationships)
        shared = sorted(left_values & right_values)
        union = left_values | right_values
        return FeatureResult(
            "knowledge_graph_relationship_similarity",
            len(shared) / len(union) if union else 0.0,
            True,
            {
                "status": "observed",
                "shared": shared,
                "left_count": len(left_values),
                "right_count": len(right_values),
            },
        )
    score, evidence = set_similarity(
        left.knowledge_graph_relationships,
        right.knowledge_graph_relationships,
    )
    return FeatureResult(
        "knowledge_graph_relationship_similarity",
        0.5 if score is None else score,
        score is not None,
        evidence,
    )
