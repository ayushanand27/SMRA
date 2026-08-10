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
    mock_mode: bool = field(default_factory=lambda: _env_bool("MOCK_MODE", False))
    groq_model: str = field(default_factory=lambda: os.getenv("GROQ_MODEL", "openai/gpt-oss-20b"))
    # gpt-oss only: low|medium|high — low cuts reasoning tokens (big latency win for demos)
    groq_reasoning_effort: str = field(
        default_factory=lambda: (os.getenv("GROQ_REASONING_EFFORT") or "low").strip().lower()
    )
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

    # Langfuse (managed tracing)
    langfuse_enabled: bool = field(default_factory=lambda: _env_bool("LANGFUSE_ENABLED", False))
    langfuse_host: str = field(default_factory=lambda: os.getenv("LANGFUSE_HOST", "https://cloud.langfuse.com"))
    langfuse_public_key: str = field(default_factory=lambda: os.getenv("LANGFUSE_PUBLIC_KEY", ""))
    langfuse_secret_key: str = field(default_factory=lambda: os.getenv("LANGFUSE_SECRET_KEY", ""))

    # API auth & rate limiting
    api_keys: List[str] = field(
        default_factory=lambda: [k.strip() for k in os.getenv("SMRA_API_KEYS", "").split(",") if k.strip()]
    )
    auth_enabled: bool = field(default_factory=lambda: _env_bool("AUTH_ENABLED", False))
    rate_limit_per_min: int = field(default_factory=lambda: _env_int("RATE_LIMIT_PER_MIN", 30))
    rate_limit_enabled: bool = field(default_factory=lambda: _env_bool("RATE_LIMIT_ENABLED", True))
    redis_url: str = field(
        default_factory=lambda: os.getenv("REDIS_URL", "redis://localhost:6379").strip()
    )

    # Deployment environment ("development" | "production"); gates strict startup checks below
    env: str = field(default_factory=lambda: (os.getenv("ENV") or "development").strip().lower())
    cors_allowed_origins: List[str] = field(
        default_factory=lambda: [
            o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:8501").split(",") if o.strip()
        ]
    )

    # Streamlit UI gate (optional shared password)
    ui_password: str = field(default_factory=lambda: os.getenv("UI_PASSWORD", ""))

    # Database (stock_prices)
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", ""))
    db_path: str = field(default_factory=lambda: os.getenv("DATABASE_PATH", str(SMRA_ROOT / "data" / "smra.db")))

    # Live ingestion (Postgres + yfinance)
    ingestion_enabled: bool = field(default_factory=lambda: _env_bool("INGESTION_ENABLED", True))
    ingestion_interval_min: int = field(default_factory=lambda: _env_int("INGESTION_INTERVAL_MIN", 30))

    # Read query TTL cache (defaults to ingestion interval)
    query_cache_enabled: bool = field(default_factory=lambda: _env_bool("QUERY_CACHE_ENABLED", True))
    cache_ttl_seconds: int = field(
        default_factory=lambda: _env_int(
            "CACHE_TTL_SECONDS",
            _env_int("INGESTION_INTERVAL_MIN", 30) * 60,
        )
    )

    # Semantic answer cache (opt-in; exact match first, then embedding similarity)
    semantic_cache_enabled: bool = field(default_factory=lambda: _env_bool("SEMANTIC_CACHE_ENABLED", False))
    semantic_cache_threshold: float = field(default_factory=lambda: _env_float("SEMANTIC_CACHE_THRESHOLD", 0.80))
    semantic_cache_ttl_seconds: int = field(default_factory=lambda: _env_int("SEMANTIC_CACHE_TTL_SECONDS", 3600))
    semantic_cache_max_entries: int = field(default_factory=lambda: _env_int("SEMANTIC_CACHE_MAX_ENTRIES", 200))

    @property
    def supported_providers(self) -> List[str]:
        return ["groq", "ollama", "gemini", "mock"]


def is_mock_mode() -> bool:
    """True when MOCK_MODE=1 or LLM_PROVIDER=mock (opt-in load/CI testing only)."""
    settings = get_settings()
    return settings.mock_mode or settings.llm_provider == "mock"


def get_settings() -> Settings:
    """Build a fresh Settings snapshot (re-reads env, useful after load_dotenv)."""
    return Settings()


def validate_production_config(settings: "Settings") -> None:
    """Fail closed if ENV=production but the API would boot without auth/rate limiting.

    Local dev / demos leave AUTH_ENABLED and RATE_LIMIT off on purpose (see .env.example);
    this only bites when an operator explicitly sets ENV=production.
    """
    if settings.env != "production":
        return
    problems = []
    if not settings.auth_enabled or not settings.api_keys:
        problems.append("AUTH_ENABLED=1 with at least one SMRA_API_KEYS entry is required")
    if not settings.rate_limit_enabled:
        problems.append("RATE_LIMIT_ENABLED=1 is required")
    if problems:
        raise RuntimeError(
            "Refusing to start with ENV=production and insecure config: "
            + "; ".join(problems)
            + ". Fix the env vars above, or unset ENV/set ENV=development for local use."
        )
