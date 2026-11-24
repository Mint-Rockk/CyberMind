import os
from uuid import uuid4

import pytest

from app.graph.client import Neo4jClient


pytestmark = pytest.mark.skipif(
    os.getenv("CYBERMIND_NEO4J_INTEGRATION") != "1",
    reason="Set CYBERMIND_NEO4J_INTEGRATION=1 to run against local Neo4j",
)


def test_controlled_graph_round_trip_is_idempotent() -> None:
    client = Neo4jClient(
        os.environ["NEO4J_URI"],
        os.environ["NEO4J_USER"],
        os.environ["NEO4J_PASSWORD"],
        os.getenv("NEO4J_DATABASE", "neo4j"),
    )
    report_id = f"CyberMindIntegrationReport:{uuid4()}"
    actor_id = f"CyberMindIntegrationActor:{uuid4()}"
    try:
        assert client.health().status == "connected"
        query = (
            "MERGE (report:ThreatReport {stable_id: $report_id}) "
            "SET report.name='controlled integration sample', "
            "report.provenance='integration-test' "
            "MERGE (actor:ThreatActor {stable_id: $actor_id}) "
            "SET actor.name='controlled integration actor' "
            "MERGE (report)-[relationship:MENTIONS]->(actor) "
            "SET relationship.relationship_origin='source_confirmed', "
            "relationship.evidence='controlled integration sample' "
            "RETURN count(report) AS reports, count(actor) AS actors, count(relationship) AS relationships"
        )
        first = client.run(query, {"report_id": report_id, "actor_id": actor_id})
        second = client.run(query, {"report_id": report_id, "actor_id": actor_id})
        assert first == second
        result = client.run(
            "MATCH (report:ThreatReport {stable_id: $report_id})"
            "-[relationship:MENTIONS]->(actor:ThreatActor {stable_id: $actor_id}) "
            "RETURN report.provenance AS provenance, relationship.evidence AS evidence",
            {"report_id": report_id, "actor_id": actor_id},
        )
        assert result == [{"provenance": "integration-test", "evidence": "controlled integration sample"}]
    finally:
        client.run(
            "MATCH (node) WHERE node.stable_id IN [$report_id, $actor_id] DETACH DELETE node",
            {"report_id": report_id, "actor_id": actor_id},
        )
        client.close()
