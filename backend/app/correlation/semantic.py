import math
from typing import Any

from app.correlation.types import FeatureResult
from app.correlation.utils import representation


def semantic_embedding_similarity(first: Any, second: Any) -> FeatureResult:
    left, right = representation(first).embedding, representation(second).embedding
    if not left or not right:
        return FeatureResult("semantic_embedding_similarity", 0.5, False, {
            "status": "missing", "reason": "both documents need compatible explicit embeddings",
        })
    if len(left) != len(right):
        return FeatureResult("semantic_embedding_similarity", 0.5, False, {
            "status": "missing", "reason": "embedding dimensions do not match",
            "left_dimensions": len(left), "right_dimensions": len(right),
        })
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0 or right_norm == 0:
        return FeatureResult("semantic_embedding_similarity", 0.5, False, {
            "status": "missing", "reason": "zero-length embedding cannot express semantic evidence",
        })
    cosine = sum(a * b for a, b in zip(left, right, strict=True)) / (left_norm * right_norm)
    return FeatureResult("semantic_embedding_similarity", max(0.0, min(1.0, (cosine + 1.0) / 2.0)), True, {
        "status": "observed", "cosine_similarity": cosine, "dimensions": len(left),
    })
