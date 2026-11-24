from typing import Final

from app.db.models import EntityType

ENTITY_NODE_LABELS: Final[dict[str, str]] = {
    EntityType.THREAT_ACTOR: "ThreatActor",
    EntityType.APT_GROUP: "ThreatActor",
    EntityType.ACTOR: "ThreatActor",
    EntityType.MALWARE: "Malware",
    EntityType.RANSOMWARE: "Malware",
    EntityType.TOOL: "Tool",
    EntityType.IP_ADDRESS: "Indicator",
    EntityType.DOMAIN: "Indicator",
    EntityType.URL: "Indicator",
    EntityType.FILE_HASH: "Indicator",
    EntityType.CVE: "Vulnerability",
    EntityType.VULNERABILITY: "Vulnerability",
    EntityType.CAMPAIGN: "Campaign",
    EntityType.SECTOR: "Sector",
    EntityType.INDICATOR: "Indicator",
}

GRAPH_NODE_LABELS: Final[tuple[str, ...]] = (
    "ThreatReport",
    "Source",
    "ThreatActor",
    "Campaign",
    "Malware",
    "Tool",
    "Indicator",
    "Vulnerability",
    "ATTACKTechnique",
    "Sector",
)

GRAPH_RELATIONSHIPS: Final[tuple[str, ...]] = (
    "REPORTED_BY",
    "MENTIONS",
    "USES",
    "ATTRIBUTED_TO",
    "ASSOCIATED_WITH",
    "EXPLOITS",
    "INDICATES",
    "TARGETS",
    "USES_TECHNIQUE",
    "RELATED_TO",
    "PART_OF_CAMPAIGN",
)


def stable_id(node_type: str, identifier: object) -> str:
    return f"{node_type}:{identifier}"


def entity_label(entity_type: str) -> str:
    return ENTITY_NODE_LABELS.get(entity_type, "Indicator")
