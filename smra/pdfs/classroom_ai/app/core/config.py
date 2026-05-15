from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # `.env` overrides `.env.example`. Only `.env` should hold real secrets (gitignored).
    model_config = SettingsConfigDict(
        env_file=(".env.example", ".env"),
        extra="ignore",
    )

    api_v1_prefix: str = "/api/v1"

    llm_provider: Literal["openai", "ollama"] = "openai"

    openai_api_key: str | None = None
    openai_chat_model: str = "gpt-4o-mini"

    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "llama3.2"
    ollama_vision_model: str = "llava"

    # Comma-separated origins for the Vite dev server (and production web app).
    cors_origins: str = "http://127.0.0.1:5173,http://localhost:5173"

    # Optional local open-source image model server (AUTOMATIC1111 / SD WebUI)
    sd_webui_url: str = "http://127.0.0.1:7860"

    # Optional: stock photos in generated slide decks (https://www.pexels.com/api/)
    pexels_api_key: str | None = None

    # Image generation stability settings
    image_generation_retries: int = 3
    image_generation_retry_delay: float = 1.0  # Initial delay in seconds
    sd_webui_seed: int = -1  # -1 for random, or specific seed for deterministic output
    llm_prompt_generation_retries: int = 3


@lru_cache
def get_settings() -> Settings:
    return Settings()
