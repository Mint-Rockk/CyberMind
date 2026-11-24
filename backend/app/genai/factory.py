from app.core.config import get_settings
from app.genai.base import LLMProvider, LLMUnavailableError
from app.genai.openai_compatible import OpenAICompatibleProvider


def create_provider() -> LLMProvider:
    settings = get_settings()
    if settings.genai_provider == "openai_compatible":
        return OpenAICompatibleProvider(
            api_key=settings.genai_api_key,
            base_url=settings.genai_base_url,
            default_model=settings.genai_model,
            timeout=settings.genai_timeout,
        )
    if settings.genai_provider == "disabled":
        raise LLMUnavailableError("GenAI provider is disabled")
    raise LLMUnavailableError(
        f"Unsupported GENAI_PROVIDER: {settings.genai_provider}"
    )
