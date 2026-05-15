"""Simple cache helpers (placeholder)

This module provides a tiny in-memory stub cache. Replace with Redis or disk-based TTL cache as needed.
"""
from functools import lru_cache
import time

@lru_cache(maxsize=128)
def cached_news(query: str, ttl_seconds: int = 3600):
    # NOTE: lru_cache doesn't support TTL; replace with real TTL cache if required.
    return {"query": query, "fetched_at": time.time(), "articles": []}
