from collections.abc import Callable

from app.collectors.base import ConnectorConfig, PublicSourceConnector
from app.collectors.connectors import (
    MITREAttackConnector,
    NVDConnector,
    OSINTResearchConnector,
    PublicAdvisoryConnector,
    RSSConnector,
    TAXIIConnector,
)
from app.db.models import SourceType

CONNECTOR_REGISTRY: dict[SourceType, type[PublicSourceConnector]] = {
    SourceType.NVD: NVDConnector,
    SourceType.MITRE_ATTACK: MITREAttackConnector,
    SourceType.RSS: RSSConnector,
    SourceType.TAXII: TAXIIConnector,
    SourceType.ADVISORY: PublicAdvisoryConnector,
    SourceType.OSINT: OSINTResearchConnector,
    SourceType.RESEARCH: OSINTResearchConnector,
}


def build_connector(source_type: SourceType, config: ConnectorConfig) -> PublicSourceConnector:
    try:
        connector_class = CONNECTOR_REGISTRY[source_type]
    except KeyError as exc:
        raise ValueError(f"No connector registered for source type {source_type}") from exc
    return connector_class(config)
