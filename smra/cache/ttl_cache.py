"""In-memory TTL cache with a swappable backend interface (Redis in Phase 4)."""
import hashlib
import json
import logging
import time
from typing import Any, Optional, Protocol

import pandas as pd

logger = logging.getLogger("smra.cache")


class CacheBackend(Protocol):
    """Replace with RedisCacheBackend in Phase 4 without changing call sites."""

    def get(self, key: str) -> Any | None: ...

    def set(self, key: str, value: Any) -> None: ...

    def clear(self) -> None: ...


class InMemoryTTLCache:
    """Thread-unsafe simple TTL store — sufficient for single-process API/Streamlit."""

    def __init__(self, ttl_seconds: int = 1800) -> None:
        self.ttl_seconds = max(1, ttl_seconds)
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str) -> Any | None:
        item = self._store.get(key)
        if item is None:
            return None
        expires, value = item
        if time.time() > expires:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        self._store[key] = (time.time() + self.ttl_seconds, value)

    def clear(self) -> None:
        self._store.clear()


def make_cache_key(sql: str, params: Optional[dict[str, Any]] = None) -> str:
    payload = {"sql": sql.strip(), "params": params or {}}
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


_query_cache: InMemoryTTLCache | None = None


def get_query_cache(ttl_seconds: int | None = None) -> InMemoryTTLCache:
    global _query_cache
    if _query_cache is None:
        ttl = ttl_seconds if ttl_seconds is not None else 1800
        _query_cache = InMemoryTTLCache(ttl_seconds=ttl)
    return _query_cache


def reset_query_cache() -> None:
    global _query_cache
    if _query_cache is not None:
        _query_cache.clear()
    _query_cache = None


def cached_read_sql(read_fn, sql: str, params: Optional[dict[str, Any]] = None) -> pd.DataFrame:
    """Wrap a read_sql callable with TTL caching for identical SELECT queries."""
    try:
        from smra.utils.config import get_settings
    except (ModuleNotFoundError, ImportError):
        from utils.config import get_settings

    settings = get_settings()
    if not settings.query_cache_enabled or not sql.strip().upper().startswith("SELECT"):
        return read_fn(sql, params)

    cache = get_query_cache(ttl_seconds=settings.cache_ttl_seconds)
    key = make_cache_key(sql, params)
    hit = cache.get(key)
    if hit is not None:
        logger.debug("Query cache hit")
        return hit.copy()

    df = read_fn(sql, params)
    cache.set(key, df.copy())
    return df
