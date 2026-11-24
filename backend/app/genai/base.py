from dataclasses import dataclass
from typing import Protocol


class LLMProviderError(RuntimeError):
    """Base error for provider configuration, transport, or response failures."""


class LLMUnavailableError(LLMProviderError):
    """Raised when a configured provider cannot be used."""


@dataclass(frozen=True)
class LLMRequest:
    system_prompt: str
    user_prompt: str
    model: str
    temperature: float = 0.0


@dataclass(frozen=True)
class LLMResponse:
    content: str
    provider: str
    model: str
    response_id: str | None
    usage: dict[str, int]


class LLMProvider(Protocol):
    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate a response for a grounded request."""
