from typing import Any

from app.correlation.attack_technique import attack_technique_similarity
from app.correlation.behavioural import behavioural_similarity
from app.correlation.entity_relationship import entity_relationship_similarity
from app.correlation.feature_schema import FEATURE_NAMES, FeatureVector, validate_feature_result
from app.correlation.knowledge_graph import knowledge_graph_relationship_similarity
from app.correlation.semantic import semantic_embedding_similarity
from app.correlation.temporal import temporal_similarity
from app.correlation.types import FeatureResult
from app.correlation.validation import validate_feature_vector


def calculate_features(first: Any, second: Any) -> FeatureVector:
    results: tuple[FeatureResult, ...] = (
        temporal_similarity(first, second),
        entity_relationship_similarity(first, second),
        behavioural_similarity(first, second),
        attack_technique_similarity(first, second),
        semantic_embedding_similarity(first, second),
        knowledge_graph_relationship_similarity(first, second),
    )
    for result in results:
        validate_feature_result(result.feature_name, result.score)
    by_name = {result.feature_name: result for result in results}
    vector = FeatureVector(
        values=tuple(by_name[name].score for name in FEATURE_NAMES),
        evidence={
            name: {
                **by_name[name].evidence,
                "available": by_name[name].available,
                "score": by_name[name].score,
            }
            for name in FEATURE_NAMES
        },
    )
    return validate_feature_vector(vector.values, evidence=vector.evidence)
