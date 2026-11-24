from datetime import datetime, timezone
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.graph.schema import entity_label, stable_id
from app.graph.client import Neo4jClient
from app.graph.sync import GraphSynchronizer


class FakeGraphClient:
    def __init__(self) -> None:
        self.queries: list[tuple[str, dict]] = []

    def run(self, query: str, parameters=None):
        self.queries.append((query, dict(parameters or {})))
        return []


def _document():
    source_id = uuid4()
    document_id = uuid4()
    entity_id = uuid4()
    technique_id = uuid4()
    campaign_id = uuid4()
    now = datetime.now(timezone.utc)
    entity = SimpleNamespace(
        id=entity_id,
        entity_type="malware",
        canonical_name="Example Malware",
        normalized_value="example-malware",
    )
    return SimpleNamespace(
        id=document_id,
        source=SimpleNamespace(id=source_id, name="Public Feed", base_url="https://feed.test"),
        normalized_title="Example report",
        title="Example report",
        original_title="Example report",
        original_url="https://feed.test/report",
        published_at=now,
        retrieved_at=now,
        provenance={"source_reference": "feed-1"},
        entity_associations=[
            SimpleNamespace(
                entity=entity,
                evidence_text="Example Malware",
                mention_text="Example Malware",
                confidence=0.9,
                extracted_at=now,
            )
        ],
        technique_mappings=[
            SimpleNamespace(
                technique=SimpleNamespace(
                    id=technique_id,
                    name="Phishing",
                    external_id="T1566",
                    tactic="initial-access",
                    dataset_version="15.1",
                ),
                evidence="T1566",
                confidence=0.95,
                mapping_status="confirmed",
            )
        ],
        campaign_associations=[
            SimpleNamespace(
                campaign=SimpleNamespace(
                    id=campaign_id,
                    name="Candidate Campaign",
                    status="candidate",
                    confidence=0.8,
                    description="Evidence-grounded candidate",
                    evidence={
                        "classification": "correlation_discovered_candidate",
                        "naming": {"status": "ai_generated", "model": "fixture-model"},
                    },
                ),
                association_evidence={"supporting_correlation_ids": ["corr-1"]},
                relevance_score=0.8,
                association_type="system_inferred",
            )
        ],
    )


def test_stable_ids_and_entity_labels_are_deterministic():
    identifier = uuid4()
    assert stable_id("ThreatReport", identifier) == f"ThreatReport:{identifier}"
    assert entity_label("threat_actor") == "ThreatActor"
    assert entity_label("unknown") == "Indicator"


def test_sync_uses_merge_and_preserves_provenance_fields():
    client = FakeGraphClient()
    synchronizer = GraphSynchronizer(client)

    result = synchronizer._write_document(_document(), [])

    assert result == {"nodes": 5, "relationships": 4}
    assert len(client.queries) == 4
    assert all("MERGE" in query for query, _ in client.queries)
    report_query, report_params = client.queries[0]
    assert "REPORTED_BY" in report_query
    assert json.loads(report_params["evidence"]) == {"source_reference": "feed-1"}
    assert "MENTIONS" in client.queries[1][0]
    assert "USES_TECHNIQUE" in client.queries[2][0]
    assert "PART_OF_CAMPAIGN" in client.queries[3][0]
    campaign_query, campaign_params = client.queries[3]
    assert "campaign.naming_metadata" in campaign_query
    assert campaign_params["classification"] == "correlation_discovered_candidate"
    assert campaign_params["naming_status"] == "ai_generated"
    assert json.loads(campaign_params["naming_metadata"])["model"] == "fixture-model"


def test_sync_writes_inferred_correlation_relationship():
    client = FakeGraphClient()
    synchronizer = GraphSynchronizer(client)
    correlation = SimpleNamespace(
        first_document_id=uuid4(),
        second_document_id=uuid4(),
        correlation_probability=0.82,
        evidence_and_explanation={"features": {"temporal_similarity": {"score": 0.9}}},
    )

    result = synchronizer._write_document(_document(), [correlation])

    assert result["relationships"] == 5
    query, params = client.queries[-1]
    assert "RELATED_TO" in query
    assert params["probability"] == 0.82
    assert json.loads(params["evidence"])["features"]


def test_graph_client_retry_count_is_positive():
    assert GraphSynchronizer(FakeGraphClient(), retries=0).retries == 1


def test_graph_client_rejects_missing_configuration():
    with pytest.raises(ValueError, match="NEO4J_URI"):
        Neo4jClient("", "neo4j", "password")
