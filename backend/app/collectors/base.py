import asyncio
import ipaddress
import logging
import re
import socket
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from pydantic import BaseModel, Field, HttpUrl
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.db.models import SourceType

logger = logging.getLogger(__name__)


class ConnectorError(RuntimeError):
    """Raised when a public source cannot be collected or parsed."""


class RetryableConnectorError(ConnectorError):
    """Raised for transient network or upstream service failures."""


class ConnectorConfig(BaseModel):
    source_type: SourceType
    endpoint_url: HttpUrl
    timeout_seconds: float = Field(default=30, gt=0, le=300)
    max_retries: int = Field(default=3, ge=1, le=6)
    rate_limit_delay_seconds: float = Field(default=0, ge=0, le=60)
    headers: dict[str, str] = Field(default_factory=dict)
    params: dict[str, str] = Field(default_factory=dict)
    api_key: str | None = None
    response_path: str | None = None
    allow_local_demo_feed: bool = False


class CollectedRecord(BaseModel):
    external_id: str
    title: str
    content: str
    source_url: str
    original_reference: str
    collected_at: datetime
    published_at: datetime | None = None
    payload: dict[str, Any]
    content_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PublicSourceConnector(ABC):
    def __init__(self, config: ConnectorConfig) -> None:
        self.config = config
        self._last_request_at: float | None = None

    async def collect(self) -> list[CollectedRecord]:
        response = await self._fetch()
        try:
            return self.parse(response)
        except Exception as exc:
            logger.exception("Failed to parse source %s", self.config.endpoint_url)
            raise ConnectorError(f"Unable to parse {self.config.endpoint_url}: {exc}") from exc

    @abstractmethod
    def parse(self, response: httpx.Response) -> list[CollectedRecord]:
        """Parse a successful public response into canonical collection records."""

    async def _fetch(self) -> httpx.Response:
        await self._respect_rate_limit()
        headers = dict(self.config.headers)
        if self.config.api_key:
            headers.setdefault("apiKey", self.config.api_key)
            headers.setdefault("X-API-Key", self.config.api_key)
        return await self._request_with_retry(
            str(self.config.endpoint_url),
            headers=headers,
            params=self.config.params,
        )

    async def _request_with_retry(
        self, url: str, *, headers: dict[str, str], params: dict[str, str]
    ) -> httpx.Response:
        retrying = AsyncRetrying(
            retry=retry_if_exception_type(
                (httpx.TimeoutException, httpx.NetworkError, RetryableConnectorError)
            ),
            wait=wait_exponential(multiplier=1, min=1, max=20),
            stop=stop_after_attempt(self.config.max_retries),
            reraise=True,
        )
        async for attempt in retrying:
            with attempt:
                return await self._request_once(url, headers=headers, params=params)
        raise ConnectorError(f"Unable to request {url}")

    async def _request_once(
        self, url: str, *, headers: dict[str, str], params: dict[str, str]
    ) -> httpx.Response:
        current_url = url
        is_local_demo_request = _is_allowed_local_demo_url(url)
        timeout = httpx.Timeout(self.config.timeout_seconds)
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
                for _ in range(5):
                    _validate_public_url(
                        current_url,
                        allow_local_demo=self.config.allow_local_demo_feed,
                    )
                    response = await client.get(
                        current_url,
                        headers=headers,
                        params=params if current_url == url else None,
                    )
                    if response.status_code not in {301, 302, 303, 307, 308}:
                        break
                    location = response.headers.get("location")
                    if not location:
                        raise ConnectorError("Source returned a redirect without a location")
                    current_url = urljoin(current_url, location)
                    if is_local_demo_request and not _is_allowed_local_demo_url(current_url):
                        raise ConnectorError("Local demo feed redirects are not allowed")
                else:
                    raise ConnectorError("Source exceeded the redirect limit")
        except (httpx.TimeoutException, httpx.NetworkError):
            logger.warning("Transient request failure for %s", url, exc_info=True)
            raise

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            delay = min(float(retry_after), 60) if retry_after and retry_after.isdigit() else 1
            await asyncio.sleep(delay)
            raise RetryableConnectorError(f"Rate limited by {url}")
        if response.status_code >= 500:
            raise RetryableConnectorError(f"Upstream failure {response.status_code} from {url}")
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise ConnectorError(f"Source returned HTTP {response.status_code}: {url}") from exc
        return response

    async def _respect_rate_limit(self) -> None:
        if self._last_request_at is None:
            self._last_request_at = asyncio.get_running_loop().time()
            return
        elapsed = asyncio.get_running_loop().time() - self._last_request_at
        delay = self.config.rate_limit_delay_seconds - elapsed
        if delay > 0:
            await asyncio.sleep(delay)
        self._last_request_at = asyncio.get_running_loop().time()


def _is_allowed_local_demo_url(value: str) -> bool:
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost"}
        or parsed.port != 8000
        or parsed.query
        or parsed.username
        or parsed.password
    ):
        return False
    return bool(
        re.fullmatch(
            r"/demo-sites/(?:cyberwatch|malwarescope|threatactor|vulntracker|aptresearch)/feed\.json",
            parsed.path,
        )
    )


def _validate_public_url(value: str, *, allow_local_demo: bool = False) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ConnectorError("Source URL must use HTTP or HTTPS with a hostname")
    if allow_local_demo and _is_allowed_local_demo_url(value):
        return
    try:
        addresses = {
            info[4][0]
            for info in socket.getaddrinfo(parsed.hostname, parsed.port, type=socket.SOCK_STREAM)
        }
    except OSError as exc:
        raise ConnectorError("Source hostname could not be resolved") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if any(
            (
                ip.is_private,
                ip.is_loopback,
                ip.is_link_local,
                ip.is_multicast,
                ip.is_reserved,
                ip.is_unspecified,
            )
        ):
            raise ConnectorError("Source URL resolves to a private or reserved address")
def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value)
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            parsed = parsedate_to_datetime(text)
        except (TypeError, ValueError):
            return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def response_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise ConnectorError("Source response was not valid JSON") from exc
