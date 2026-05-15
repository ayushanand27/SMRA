from typing import Literal

from app.core.config import Settings, get_settings
from app.services.llm.ollama_provider import OllamaProvider
from app.services.llm.openai_provider import OpenAIProvider
from app.services.llm.protocol import LLMProvider


def get_llm_provider(
    *,
    vision: bool = False,
    settings: Settings | None = None,
    provider: Literal["openai", "ollama"] | None = None,
) -> LLMProvider:
    s = settings or get_settings()
    selected = provider or s.llm_provider
    if selected == "openai":
        return OpenAIProvider(s)
    return OllamaProvider(s, vision=vision)
