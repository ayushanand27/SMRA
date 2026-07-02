"""Centralized configuration loaded from environment variables.

Keeps env parsing in one place so agents/scripts stay clean and testable.
"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

SMRA_ROOT = Path(__file__).resolve().parents[1]


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


@dataclass
class Settings:
    # LLM
    llm_provider: str = field(default_factory=lambda: (os.getenv("LLM_PROVIDER") or "groq").strip().lower())
    groq_model: str = field(default_factory=lambda: os.getenv("GROQ_MODEL", "mixtral-8x7b-32768"))
    ollama_url: str = field(default_factory=lambda: os.getenv("OLLAMA_URL", "http://localhost:11434"))
    ollama_model: str = field(default_factory=lambda: os.getenv("OLLAMA_MODEL", "llama3.1"))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-1.5-flash"))
    llm_max_tokens: int = field(default_factory=lambda: _env_int("LLM_MAX_TOKENS", 1000))
    llm_temperature: float = field(default_factory=lambda: _env_float("LLM_TEMPERATURE", 0.0))

    # Retrieval / RAG
    rag_top_k: int = field(default_factory=lambda: _env_int("RAG_TOP_K", 4))
    rag_score_threshold: float = field(default_factory=lambda: _env_float("RAG_SCORE_THRESHOLD", 0.5))
    pinecone_disabled: bool = field(default_factory=lambda: _env_bool("PINECONE_DISABLED", False))
    pinecone_index: str = field(default_factory=lambda: os.getenv("PINECONE_INDEX", "smra-index"))
    embedding_model: str = field(
        default_factory=lambda: os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
    )

    # Guardrails
    max_input_chars: int = field(default_factory=lambda: _env_int("MAX_INPUT_CHARS", 2000))
    guardrails_enabled: bool = field(default_factory=lambda: _env_bool("GUARDRAILS_ENABLED", True))

    # Observability
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    json_logs: bool = field(default_factory=lambda: _env_bool("JSON_LOGS", False))

    # Paths
    db_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", str(SMRA_ROOT / "data" / "smra.db")))

    @property
    def supported_providers(self) -> List[str]:
        return ["groq", "ollama", "gemini"]


def get_settings() -> Settings:
    """Build a fresh Settings snapshot (re-reads env, useful after load_dotenv)."""
    return Settings()
