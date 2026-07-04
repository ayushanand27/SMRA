"""Config-driven database access for stock_prices.

Uses SQLAlchemy Engine (no ORM) so the same code path works for:
- SQLite when DATABASE_URL is unset (local dev fallback)
- Postgres when DATABASE_URL is set (production / concurrent writers)

pandas.read_sql + sqlalchemy.text keeps the SQL agent's SELECT-only flow unchanged.
"""
import logging
from pathlib import Path
from typing import Any, Optional

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

_ENV = Path(__file__).resolve().parents[1] / ".env"
if _ENV.exists():
    load_dotenv(_ENV, override=True)

try:
    from smra.utils.config import get_settings
except (ModuleNotFoundError, ImportError):
    from utils.config import get_settings

logger = logging.getLogger("smra.db")

_engine: Optional[Engine] = None


def get_database_url() -> str:
    """Resolve DATABASE_URL or fall back to SQLite file from settings."""
    settings = get_settings()
    url = (settings.database_url or "").strip()
    if url:
        return url
    path = settings.db_path.replace("\\", "/")
    return f"sqlite:///{path}"


def is_postgres() -> bool:
    return get_database_url().startswith("postgresql")


def log_backend_status() -> str:
    """Log and return which DB backend is active (call at API/scheduler startup)."""
    settings = get_settings()
    if is_postgres():
        safe = get_database_url().split("@")[-1]
        msg = f"DB backend: Postgres ({safe})"
    else:
        msg = f"DB backend: SQLite fallback ({settings.db_path})"
    logger.info(msg)
    return msg


def get_engine() -> Engine:
    """Return a cached SQLAlchemy engine (pool_pre_ping for Postgres resilience)."""
    global _engine
    if _engine is None:
        url = get_database_url()
        connect_args = {}
        if url.startswith("sqlite"):
            connect_args["check_same_thread"] = False
        _engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
        safe = url.split("@")[-1] if "@" in url else url
        backend = "Postgres" if url.startswith("postgresql") else "SQLite"
        logger.info("DB engine initialized [%s] (%s)", backend, safe)
        if url.startswith("postgresql"):
            try:
                from smra.ingestion.upsert import ensure_currency_column
            except (ModuleNotFoundError, ImportError):
                from ingestion.upsert import ensure_currency_column
            ensure_currency_column()
    return _engine


def reset_engine() -> None:
    """Dispose cached engine (tests / env reload)."""
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def read_sql_query(sql: str, params: Optional[dict[str, Any]] = None) -> pd.DataFrame:
    """Run a read-only SELECT and return a DataFrame (optional TTL cache)."""

    def _execute(query: str, bind: Optional[dict[str, Any]]) -> pd.DataFrame:
        engine = get_engine()
        with engine.connect() as conn:
            return pd.read_sql(text(query), conn, params=bind or {})

    try:
        from smra.cache.ttl_cache import cached_read_sql
    except (ModuleNotFoundError, ImportError):
        from cache.ttl_cache import cached_read_sql

    return cached_read_sql(_execute, sql, params)


def scalar_query(sql: str, params: Optional[dict[str, Any]] = None) -> Any:
    """Run a query that returns a single scalar value."""
    engine = get_engine()
    with engine.connect() as conn:
        row = conn.execute(text(sql), params or {}).fetchone()
        return row[0] if row else None
