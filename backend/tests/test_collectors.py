import json
from datetime import datetime, timezone

import feedparser
import httpx
import pytest
import stix2

from app.collectors.base import ConnectorConfig
from app.collectors.base import ConnectorError, _validate_public_url
from app.collectors.connectors import (
    MITREAttackConnector,
    NVDConnector,
    OSINTResearchConnector,
    PublicAdvisoryConnector,
    RSSConnector,
    TAXIIConnector,
)
from app.db.models import SourceType


def response(payload, content_type="application/json") -> httpx.Response:
    return httpx.Response(200, json=payload, headers={"content-type": content_type})


def test_nvd_connector_normalizes_cve_records() -> None:
    connector = NVDConnector(
        ConnectorConfig(source_type=SourceType.NVD, endpoint_url="https://example.test/nvd")
    )
    records = connector.parse(
        response(
            {
                "vulnerabilities": [
                    {
                        "cve": {
                            "id": "CVE-2026-0001",
                            "published": "2026-01-01T00:00:00Z",
                            "descriptions": [{"lang": "en", "value": "Example vulnerability"}],
                            "references": [{"url": "https://example.test/CVE-2026-0001"}],
                        }
                    }
                ]
            }
        )
    )
    assert records[0].external_id == "CVE-2026-0001"
    assert records[0].original_reference.endswith("CVE-2026-0001")


def test_mitre_and_taxii_connectors_validate_stix_objects() -> None:
    attack_pattern = stix2.AttackPattern(
        name="Example Technique",
        description="A public fixture technique.",
        external_references=[{"source_name": "mitre-attack", "external_id": "T0001"}],
    )
    bundle = {"objects": [json.loads(attack_pattern.serialize())]}
    config = ConnectorConfig(
        source_type=SourceType.MITRE_ATTACK, endpoint_url="https://example.test/attack.json"
    )
    records = MITREAttackConnector(config).parse(response(bundle, "application/stix+json"))
    assert records[0].metadata["stix_type"] == "attack-pattern"
    taxii_config = config.model_copy(update={"source_type": SourceType.TAXII})
    taxii_records = TAXIIConnector(taxii_config).parse(
        response(bundle, "application/taxii+json;version=2.1")
    )
    assert taxii_records[0].content_type.startswith("application/taxii+json")


def test_rss_and_generic_public_sources_produce_structured_records() -> None:
    rss = """<?xml version="1.0"?><rss version="2.0"><channel><title>Fixture Feed</title>
    <item><guid>fixture-1</guid><title>Public advisory</title>
    <link>https://example.test/advisory/1</link><description>Public content</description>
    <pubDate>Mon, 01 Jan 2026 00:00:00 GMT</pubDate></item></channel></rss>"""
    rss_config = ConnectorConfig(
        source_type=SourceType.RSS, endpoint_url="https://example.test/feed.xml"
    )
    rss_records = RSSConnector(rss_config).parse(
        httpx.Response(200, content=rss.encode(), headers={"content-type": "application/rss+xml"})
    )
    assert rss_records[0].external_id == "fixture-1"
    assert rss_records[0].published_at == datetime(2026, 1, 1, tzinfo=timezone.utc)

    advisory_config = ConnectorConfig(
        source_type=SourceType.ADVISORY, endpoint_url="https://example.test/advisories"
    )
    generic_response = response({"advisories": [{"id": "ADV-1", "title": "Advisory", "description": "Details"}]})
    assert PublicAdvisoryConnector(advisory_config).parse(generic_response)[0].external_id == "ADV-1"
    osint_config = advisory_config.model_copy(update={"source_type": SourceType.OSINT})
    assert OSINTResearchConnector(osint_config).parse(generic_response)[0].metadata["source"] == "advisory"


def test_local_demo_connector_uses_article_reference_and_exact_url_allowlist() -> None:
    config = ConnectorConfig(
        source_type=SourceType.ADVISORY,
        endpoint_url="http://127.0.0.1:8000/demo-sites/cyberwatch/feed.json",
        response_path="items",
        allow_local_demo_feed=True,
    )
    article_url = "http://127.0.0.1:8000/demo-sites/cyberwatch/reports/CW-1"
    records = PublicAdvisoryConnector(config).parse(
        response({
            "items": [{
                "id": "CW-1",
                "title": "Fictional report",
                "content": "Fictional evidence text.",
                "url": article_url,
                "fictional_demo": True,
            }]
        })
    )
    assert records[0].source_url == article_url
    _validate_public_url(str(config.endpoint_url), allow_local_demo=True)
    with pytest.raises(ConnectorError, match="private or reserved"):
        _validate_public_url(
            "http://127.0.0.1:8000/demo-sites/cyberwatch/reports/CW-1",
            allow_local_demo=True,
        )


@pytest.mark.asyncio
async def test_osint_research_connector_feed_discovery() -> None:
    html = """<!DOCTYPE html><html><head>
    <link rel="alternate" type="application/rss+xml" href="https://example.test/feed.xml" />
    </head><body><a href="/en/rss/feed/">Feed</a></body></html>"""
    rss = """<?xml version="1.0"?><rss version="2.0"><channel><title>Research Feed</title>
    <item><guid>research-1</guid><title>Research Article</title>
    <link>https://example.test/research/1</link><description>Threat analysis</description>
    <pubDate>Mon, 01 Jan 2026 00:00:00 GMT</pubDate></item></channel></rss>"""

    research_config = ConnectorConfig(
        source_type=SourceType.RESEARCH, endpoint_url="https://example.test"
    )
    connector = OSINTResearchConnector(research_config)

    html_resp = httpx.Response(200, content=html.encode(), headers={"content-type": "text/html"})
    feed_resp = httpx.Response(200, content=rss.encode(), headers={"content-type": "application/rss+xml"})

    async def mock_fetch():
        return html_resp

    async def mock_request_with_retry(url, headers, params):
        return feed_resp

    connector._fetch = mock_fetch
    connector._request_with_retry = mock_request_with_retry

    records = await connector.collect()
    assert len(records) == 1
    assert records[0].external_id == "research-1"
    assert records[0].title == "Research Article"

