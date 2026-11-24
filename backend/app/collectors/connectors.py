import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import feedparser
import httpx
import stix2

from app.collectors.base import (
    CollectedRecord,
    ConnectorConfig,
    ConnectorError,
    PublicSourceConnector,
    parse_datetime,
    response_json,
)

logger = logging.getLogger(__name__)


class NVDConnector(PublicSourceConnector):
    def parse(self, response: httpx.Response) -> list[CollectedRecord]:
        payload = response_json(response)
        records: list[CollectedRecord] = []
        for vulnerability in payload.get("vulnerabilities", []):
            cve = vulnerability.get("cve", {})
            cve_id = cve.get("id")
            if not cve_id:
                continue
            descriptions = cve.get("descriptions", [])
            description = next(
                (item.get("value", "") for item in descriptions if item.get("lang") == "en"),
                descriptions[0].get("value", "") if descriptions else "",
            )
            references = [item.get("url") for item in cve.get("references", []) if item.get("url")]
            records.append(
                CollectedRecord(
                    external_id=cve_id,
                    title=cve_id,
                    content=description,
                    source_url=str(self.config.endpoint_url),
                    original_reference=references[0] if references else str(self.config.endpoint_url),
                    collected_at=datetime.now(timezone.utc),
                    published_at=parse_datetime(cve.get("published")),
                    payload=vulnerability,
                    content_type="application/json",
                    metadata={"source": "nvd", "references": references},
                )
            )
        return records


class MITREAttackConnector(PublicSourceConnector):
    def parse(self, response: httpx.Response) -> list[CollectedRecord]:
        payload = response_json(response)
        records: list[CollectedRecord] = []
        for item in payload.get("objects", []):
            if item.get("type") not in {"attack-pattern", "campaign", "intrusion-set", "malware", "tool"}:
                continue
            try:
                stix_object = stix2.parse(item, allow_custom=True)
            except Exception as exc:
                raise ConnectorError(f"Invalid STIX object {item.get('id')}") from exc
            external_id = item.get("id")
            if not external_id:
                continue
            records.append(
                CollectedRecord(
                    external_id=external_id,
                    title=item.get("name", external_id),
                    content=item.get("description", ""),
                    source_url=str(self.config.endpoint_url),
                    original_reference=item.get("external_references", [{}])[0].get(
                        "url", str(self.config.endpoint_url)
                    ),
                    collected_at=datetime.now(timezone.utc),
                    published_at=parse_datetime(item.get("created")),
                    payload=json.loads(stix_object.serialize()),
                    content_type="application/stix+json",
                    metadata={"stix_type": item.get("type"), "modified": item.get("modified")},
                )
            )
        return records


class RSSConnector(PublicSourceConnector):
    def parse(self, response: httpx.Response) -> list[CollectedRecord]:
        parsed = feedparser.parse(response.content)
        records: list[CollectedRecord] = []
        for entry in parsed.entries:
            external_id = str(entry.get("id") or entry.get("link") or entry.get("title", "")).strip()
            if not external_id:
                continue
            content = str(entry.get("summary") or entry.get("description") or "")
            records.append(
                CollectedRecord(
                    external_id=external_id,
                    title=str(entry.get("title") or external_id),
                    content=content,
                    source_url=str(self.config.endpoint_url),
                    original_reference=str(entry.get("link") or self.config.endpoint_url),
                    collected_at=datetime.now(timezone.utc),
                    published_at=parse_datetime(entry.get("published") or entry.get("updated")),
                    payload={key: value for key, value in dict(entry).items() if isinstance(value, (str, int, float, list, dict))},
                    content_type="application/rss+xml",
                    metadata={"feed_title": parsed.feed.get("title", "")},
                )
            )
        return records


class TAXIIConnector(PublicSourceConnector):
    def parse(self, response: httpx.Response) -> list[CollectedRecord]:
        payload = response_json(response)
        objects = payload.get("objects", [])
        if not isinstance(objects, list):
            raise ConnectorError("TAXII response did not contain an objects list")
        records: list[CollectedRecord] = []
        for item in objects:
            try:
                stix_object = stix2.parse(item, allow_custom=True)
            except Exception as exc:
                raise ConnectorError(f"Invalid TAXII STIX object {item.get('id')}") from exc
            object_id = item.get("id")
            if not object_id:
                continue
            records.append(
                CollectedRecord(
                    external_id=object_id,
                    title=item.get("name", object_id),
                    content=item.get("description", ""),
                    source_url=str(self.config.endpoint_url),
                    original_reference=item.get("external_references", [{}])[0].get(
                        "url", str(self.config.endpoint_url)
                    ),
                    collected_at=datetime.now(timezone.utc),
                    published_at=parse_datetime(item.get("created")),
                    payload=json.loads(stix_object.serialize()),
                    content_type="application/taxii+json;version=2.1",
                    metadata={"stix_type": item.get("type"), "taxii_version": "2.1"},
                )
            )
        return records


class PublicAdvisoryConnector(PublicSourceConnector):
    def parse(self, response: httpx.Response) -> list[CollectedRecord]:
        if "xml" in response.headers.get("content-type", "").lower():
            return RSSConnector(self.config).parse(response)
        payload = response_json(response)
        items: Any = payload
        if self.config.response_path:
            for part in self.config.response_path.split("."):
                if not isinstance(items, dict):
                    items = []
                    break
                items = items.get(part, [])
        elif isinstance(payload, dict):
            items = payload.get("advisories") or payload.get("items") or payload.get("data") or []
        if not isinstance(items, list):
            raise ConnectorError("Advisory response did not contain a list")
        return _records_from_generic_items(items, self.config, "advisory")


class OSINTResearchConnector(PublicAdvisoryConnector):
    async def collect(self) -> list[CollectedRecord]:
        response = await self._fetch()
        content_type = response.headers.get("content-type", "").lower()
        if (
            "xml" in content_type
            or response.content.startswith(b"<?xml")
            or b"<rss" in response.content[:300]
            or b"<feed" in response.content[:300]
        ):
            return RSSConnector(self.config).parse(response)

        if "html" in content_type:
            discovered = await self._discover_and_collect_feed(response)
            if discovered:
                return discovered

        try:
            return self.parse(response)
        except Exception as exc:
            logger.exception("Failed to parse source %s", self.config.endpoint_url)
            raise ConnectorError(f"Unable to parse {self.config.endpoint_url}: {exc}") from exc

    async def _discover_and_collect_feed(self, response: httpx.Response) -> list[CollectedRecord] | None:
        soup = BeautifulSoup(response.text, "html.parser")
        candidates: list[str] = []

        for link in soup.find_all("link", rel=lambda x: x and "alternate" in x):
            link_type = link.get("type", "").lower()
            if any(t in link_type for t in ["rss", "xml", "atom"]):
                href = link.get("href")
                if href:
                    candidates.append(href)

        for a in soup.find_all("a", href=re.compile(r"/feed|/rss|rss\.xml|atom\.xml|/feed/", re.I)):
            href = a.get("href")
            if href:
                candidates.append(href)

        for fallback in ["/feed/", "/rss/", "/en/rss/feed/", "/rss.xml", "/feed"]:
            candidates.append(fallback)

        seen: set[str] = set()
        base_url = str(response.url) if getattr(response, "_request", None) is not None else str(self.config.endpoint_url)
        for candidate in candidates:
            target_url = urljoin(base_url, candidate)
            if target_url in seen:
                continue
            seen.add(target_url)

            try:
                feed_response = await self._request_with_retry(
                    target_url,
                    headers=self.config.headers,
                    params={},
                )
                if feed_response.status_code == 200:
                    feed_config = self.config.model_copy(update={"endpoint_url": target_url})
                    records = RSSConnector(feed_config).parse(feed_response)
                    if records:
                        return records
            except Exception:
                continue

        return None

    def parse(self, response: httpx.Response) -> list[CollectedRecord]:
        return super().parse(response)


def _records_from_generic_items(
    items: list[dict[str, Any]], config: ConnectorConfig, category: str
) -> list[CollectedRecord]:
    records: list[CollectedRecord] = []
    for item in items:
        external_id = str(item.get("id") or item.get("identifier") or item.get("url") or "").strip()
        if not external_id:
            continue
        article_url = str(item.get("url") or config.endpoint_url)
        source_url = (
            article_url
            if config.allow_local_demo_feed and item.get("fictional_demo") is True
            else str(config.endpoint_url)
        )
        records.append(
            CollectedRecord(
                external_id=external_id,
                title=str(item.get("title") or item.get("name") or external_id),
                content=str(item.get("description") or item.get("summary") or item.get("content") or ""),
                source_url=source_url,
                original_reference=article_url,
                collected_at=datetime.now(timezone.utc),
                published_at=parse_datetime(item.get("published") or item.get("published_at")),
                payload=item,
                content_type="application/json",
                metadata={"source": category},
            )
        )
    return records
