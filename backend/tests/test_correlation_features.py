from datetime import datetime, timedelta, timezone

import pytest

from app.correlation.attack_technique import attack_technique_similarity
from app.correlation.behavioural import behavioural_similarity
from app.correlation.behavioural import extract_behaviour_evidence
from app.correlation.entity_relationship import entity_relationship_similarity
from app.correlation.feature_schema import (
    FEATURE_NAMES,
    FEATURE_SCHEMA_VERSION,
    MISSING_VALUE_POLICY,
)
from app.correlation.knowledge_graph import knowledge_graph_relationship_similarity
from app.correlation.semantic import semantic_embedding_similarity
from app.correlation.service import calculate_features
from app.correlation.temporal import temporal_similarity
from app.correlation.types import DocumentRepresentation
from app.correlation.validation import validate_feature_vector


NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


def test_temporal_similarity_uses_overlapping_activity_windows() -> None:
    first = DocumentRepresentation(activity_start=NOW, activity_end=NOW + timedelta(days=2))
    second = DocumentRepresentation(activity_start=NOW + timedelta(days=1), activity_end=NOW + timedelta(days=3))

    result = temporal_similarity(first, second)

    assert result.score == pytest.approx(1 / 3)
    assert result.available is True
    assert result.evidence["status"] == "observed"


@pytest.mark.parametrize(
    ("service", "first", "second", "expected"),
    [
        (entity_relationship_similarity, {"entities": ["APT28", "CVE-1"]}, {"entities": ["apt28", "CVE-2"]}, 1 / 3),
        (behavioural_similarity, {"behaviours": ["credential dumping", "phishing"]}, {"behaviours": ["phishing"]}, 1 / 2),
        (attack_technique_similarity, {"attack_techniques": ["T1059", "T1566"]}, {"attack_techniques": ["T1566"]}, 1 / 2),
        (
            knowledge_graph_relationship_similarity,
            {"knowledge_graph_relationships": [("apt28", "uses", "x") , ("apt28", "targets", "energy")]},
            {"knowledge_graph_relationships": [("apt28", "targets", "energy")]},
            1 / 2,
        ),
    ],
)
def test_set_based_features_return_evidence(service, first, second, expected) -> None:
    result = service(first, second)
    assert result.score == pytest.approx(expected)
    assert result.available is True
    assert result.evidence["shared"]


def test_semantic_similarity_normalizes_explicit_embeddings() -> None:
    result = semantic_embedding_similarity({"embedding": [1.0, 0.0]}, {"embedding": [1.0, 0.0]})

    assert result.score == 1.0
    assert result.evidence["cosine_similarity"] == pytest.approx(1.0)


def test_behaviour_extraction_is_explicit_and_distinct_from_attack_ids() -> None:
    evidence = extract_behaviour_evidence(
        "The operator used spear-phishing emails, dumped credentials, and "
        "captured a screenshot while the malware connected to a command-and-control server. "
        "The report also references T1566."
    )

    values = {item.value for item in evidence}
    assert "initial_access:spear_phishing" in values
    assert "credential_access:credential_dumping" in values
    assert "collection:screenshot" in values
    assert "command_control:command_and_control" in values
    assert all(not value.startswith("T") for value in values)
    assert all(item.evidence_text for item in evidence)


def test_behaviour_extraction_keeps_missing_reports_unavailable() -> None:
    assert extract_behaviour_evidence("This report contains no explicit action description.") == ()
    result = behavioural_similarity({}, {"behaviours": ()})
    assert result.score == 0.5
    assert result.available is False


def test_missing_evidence_is_neutral_but_explicitly_unavailable() -> None:
    result = semantic_embedding_similarity({}, {"embedding": [1.0, 0.0]})

    assert result.score == 0.5
    assert result.available is False
    assert result.evidence["status"] == "missing"


@pytest.mark.parametrize(
    ("first", "second", "available"),
    [
        (
            {"knowledge_graph_relationships": [("report-a", "mentions", "malware-x")]},
            {"knowledge_graph_relationships": [("report-b", "mentions", "malware-x")]},
            True,
        ),
        ({}, {"knowledge_graph_relationships": [("report-b", "mentions", "malware-x")]}, False),
        (
            {"knowledge_graph_relationships": [("actor-a", "uses", "tool-x")]},
            {"knowledge_graph_relationships": [("actor-a", "uses", "tool-x")]},
            True,
        ),
    ],
)
def test_knowledge_graph_similarity_is_explicit_about_graph_evidence(
    first, second, available
) -> None:
    result = knowledge_graph_relationship_similarity(first, second)
    assert result.available is available
    assert 0 <= result.score <= 1


def test_same_actor_without_shared_relationship_is_not_graph_similarity() -> None:
    result = knowledge_graph_relationship_similarity(
        {"knowledge_graph_relationships": [("actor-a", "mentions", "malware-a")]},
        {"knowledge_graph_relationships": [("actor-a", "mentions", "malware-b")]},
    )
    assert result.score == 0
    assert result.available is True
    assert result.evidence["shared"] == []


def test_graph_coverage_distinguishes_empty_graph_from_failed_lookup() -> None:
    observed = knowledge_graph_relationship_similarity(
        {"knowledge_graph_relationships": [], "metadata": {"knowledge_graph_available": True}},
        {"knowledge_graph_relationships": [], "metadata": {"knowledge_graph_available": True}},
    )
    missing = knowledge_graph_relationship_similarity(
        {"metadata": {"knowledge_graph_available": False}},
        {"knowledge_graph_relationships": [], "metadata": {"knowledge_graph_available": True}},
    )
    assert observed.score == 0.0
    assert observed.available is True
    assert missing.score == 0.5
    assert missing.available is False


def test_aggregator_preserves_exact_schema_order_and_no_extra_inputs() -> None:
    vector = calculate_features(
        DocumentRepresentation(
            published_at=NOW,
            entities=("APT28",),
            behaviours=("phishing",),
            attack_techniques=("T1566",),
            embedding=(1.0, 0.0),
        ),
        DocumentRepresentation(
            published_at=NOW,
            entities=("apt28",),
            behaviours=("phishing",),
            attack_techniques=("T1566",),
            embedding=(1.0, 0.0),
        ),
    )

    assert vector.schema_version == FEATURE_SCHEMA_VERSION
    assert len(vector.values) == 6
    assert tuple(vector.evidence) == FEATURE_NAMES
    assert vector.as_model_input() == pytest.approx((1, 1, 1, 1, 1, 0.5))
    assert MISSING_VALUE_POLICY["model_vector"].startswith("Materialize missing")


def test_mismatched_embedding_dimensions_are_missing_not_zero() -> None:
    result = semantic_embedding_similarity({"embedding": [1.0]}, {"embedding": [1.0, 0.0]})

    assert result.score == 0.5
    assert result.available is False
    assert "dimensions" in result.evidence["reason"]


def test_feature_validation_rejects_wrong_schema_and_value_count() -> None:
    with pytest.raises(ValueError, match="unsupported feature schema"):
        validate_feature_vector([0.0] * 6, schema_version="correlation-features-v0")
    with pytest.raises(ValueError, match="exactly six"):
        validate_feature_vector([0.0] * 5)
