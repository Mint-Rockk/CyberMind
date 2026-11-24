import asyncio
import logging
from typing import Any

import httpx

from app.genai.base import LLMRequest, LLMResponse, LLMUnavailableError

logger = logging.getLogger(__name__)

_TRANSIENT_STATUS_CODES = {429, 502, 503, 504}
_MAX_RETRIES = 3


class OpenAICompatibleProvider:
    """Small HTTP provider adapter for OpenAI-compatible chat-completion APIs."""

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str,
        default_model: str,
        timeout: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise LLMUnavailableError("GENAI_API_KEY is not configured")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model
        self.timeout = timeout
        self._client = client

    async def generate(self, request: LLMRequest) -> LLMResponse:
        owns_client = self._client is None
        timeout = httpx.Timeout(self.timeout, connect=10.0, read=self.timeout, write=10.0, pool=10.0)
        client = self._client or httpx.AsyncClient(timeout=timeout)
        payload: dict[str, Any] | None = None

        try:
            for attempt in range(1, _MAX_RETRIES + 1):
                try:
                    response = await client.post(
                        f"{self.base_url}/chat/completions",
                        headers={
                            "Authorization": f"Bearer {self.api_key}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "model": request.model or self.default_model,
                            "temperature": request.temperature,
                            "messages": [
                                {"role": "system", "content": request.system_prompt},
                                {"role": "user", "content": request.user_prompt},
                            ],
                            "response_format": {"type": "json_object"},
                        },
                    )
                    response.raise_for_status()
                    payload = response.json()
                    break
                except httpx.HTTPStatusError as exc:
                    status_code = exc.response.status_code
                    if status_code in _TRANSIENT_STATUS_CODES and attempt < _MAX_RETRIES:
                        backoff = min(1.0 * (2 ** (attempt - 1)), 5.0)
                        logger.warning(
                            "Transient provider HTTP %d on attempt %d/%d; retrying in %.1fs",
                            status_code,
                            attempt,
                            _MAX_RETRIES,
                            backoff,
                        )
                        await asyncio.sleep(backoff)
                        continue
                    if status_code in _TRANSIENT_STATUS_CODES:
                        raise LLMUnavailableError(
                            f"LLM provider service temporarily unavailable (HTTP {status_code}) after {_MAX_RETRIES} attempts"
                        ) from exc
                    raise LLMUnavailableError(
                        f"LLM provider request failed (HTTP {status_code})"
                    ) from exc
                except httpx.TimeoutException as exc:
                    if attempt < _MAX_RETRIES:
                        backoff = min(1.0 * (2 ** (attempt - 1)), 5.0)
                        logger.warning(
                            "Provider request timed out on attempt %d/%d; retrying in %.1fs",
                            attempt,
                            _MAX_RETRIES,
                            backoff,
                        )
                        await asyncio.sleep(backoff)
                        continue
                    raise LLMUnavailableError(
                        f"LLM provider request timed out after {_MAX_RETRIES} attempts"
                    ) from exc
                except httpx.RequestError as exc:
                    raise LLMUnavailableError(
                        f"LLM provider network request failed ({type(exc).__name__})"
                    ) from exc
                except ValueError as exc:
                    raise LLMUnavailableError("LLM provider returned invalid JSON") from exc
        finally:
            if owns_client:
                await client.aclose()

        if not isinstance(payload, dict):
            raise LLMUnavailableError("LLM provider returned an invalid JSON object")
        content = _content(payload)
        if not content:
            raise LLMUnavailableError("LLM provider returned empty content")
        usage = payload.get("usage") or {}
        return LLMResponse(
            content=content,
            provider="openai_compatible",
            model=str(payload.get("model") or request.model or self.default_model),
            response_id=str(payload["id"]) if payload.get("id") else None,
            usage={
                key: int(value)
                for key, value in usage.items()
                if key in {"prompt_tokens", "completion_tokens", "total_tokens"}
            },
        )


def _content(payload: dict[str, Any]) -> str | None:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message")
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    return content if isinstance(content, str) else None
