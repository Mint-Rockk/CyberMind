from typing import Any

from app.graph.client import Neo4jClient
from app.graph.schema import GRAPH_NODE_LABELS, stable_id


class GraphQueryService:
    """Predefined, parameterized graph reads; arbitrary Cypher is not exposed."""

    def __init__(self, client: Neo4jClient) -> None:
        self.client = client

    def status(self) -> dict[str, str | None]:
        health = self.client.health()
        return {
            "status": health.status,
            "database": health.database,
            "detail": health.detail,
        }

    def search(self, query: str, label: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        selected_label = label if label in GRAPH_NODE_LABELS else None
        match = f"(node:{selected_label})" if selected_label else "(node)"
        cypher = (
            f"MATCH {match} "
            "WHERE node.name IS NOT NULL AND "
            "toLower(node.name) CONTAINS toLower($query) "
            "RETURN node ORDER BY node.name LIMIT $limit"
        )
        return self.client.run(cypher, {"query": query, "limit": limit})

    def neighborhood(self, stable_node_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return self.client.run(
            "MATCH (node {stable_id: $stable_id})-[relationship]-(neighbor) "
            "RETURN node, relationship, neighbor LIMIT $limit",
            {"stable_id": stable_node_id, "limit": limit},
        )

    def report_context(self, report_id: str, limit: int = 100) -> list[dict[str, Any]]:
        return self.neighborhood(f"ThreatReport:{report_id}", limit)

    def relationship_triples(self, report_id: object, limit: int = 300) -> tuple[tuple[str, str, str], ...]:
        rows = self.client.run(
            "MATCH (report:ThreatReport {stable_id: $stable_id})-[relationship]-(neighbor) "
            "WHERE coalesce(relationship.relationship_origin, '') <> 'demo_ground_truth' "
            "AND NOT 'Campaign' IN labels(neighbor) "
            "RETURN labels(neighbor) AS labels, type(relationship) AS predicate, "
            "coalesce(neighbor.normalized_value, neighbor.external_id, neighbor.name, "
            "neighbor.stable_id) AS object LIMIT $limit",
            {"stable_id": stable_id("ThreatReport", report_id), "limit": limit},
        )
        return tuple(sorted({
            (
                str((row.get("labels") or ["Entity"])[0]),
                str(row.get("predicate") or "RELATED_TO"),
                str(row.get("object") or ""),
            )
            for row in rows
            if row.get("object")
        }))

    def campaign_subgraph(self, campaign_id: str, limit: int = 200) -> list[dict[str, Any]]:
        return self.neighborhood(f"Campaign:{campaign_id}", limit)
