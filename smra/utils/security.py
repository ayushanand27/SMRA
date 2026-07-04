"""API authentication and rate limiting.

- API-key auth via the `X-API-Key` header (constant-time comparison).
- Sliding-window rate limiter keyed by API key or client IP.
  Uses Redis when REDIS_URL is reachable; falls back to in-memory per process.

Both controls are config-gated so local dev stays frictionless.
"""
import hmac
import logging
import threading
import time
import uuid
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

try:
    from smra.utils.config import get_settings
except (ModuleNotFoundError, ImportError):
    from utils.config import get_settings

logger = logging.getLogger("smra.security")

_lock = threading.Lock()
_hits: Dict[str, Deque[float]] = defaultdict(deque)

_redis_client = None
_redis_fallback_logged = False

_RATE_LIMIT_KEY_PREFIX = "smra:ratelimit:"


def verify_api_key(provided: Optional[str]) -> bool:
    """Constant-time check of an API key against the configured allow-list."""
    settings = get_settings()
    if not settings.auth_enabled:
        return True
    if not settings.api_keys:
        # Auth turned on but no keys configured: fail closed.
        return False
    if not provided:
        return False
    return any(hmac.compare_digest(provided, key) for key in settings.api_keys)


def _redis_url_enabled(url: str) -> bool:
    normalized = (url or "").strip().lower()
    return normalized not in {"", "none", "memory", "disabled", "0", "false"}


def _get_redis_client():
    """Return a cached Redis client, or None if Redis is disabled/unreachable."""
    global _redis_client, _redis_fallback_logged

    settings = get_settings()
    if not _redis_url_enabled(settings.redis_url):
        return None

    if _redis_client is not None:
        return _redis_client

    try:
        import redis

        client = redis.from_url(
            settings.redis_url,
            decode_responses=True,
            socket_connect_timeout=1.0,
            socket_timeout=1.0,
        )
        client.ping()
        _redis_client = client
        safe = settings.redis_url.split("@")[-1] if "@" in settings.redis_url else settings.redis_url
        logger.info("Rate limiter using Redis (%s)", safe)
        return _redis_client
    except Exception as exc:
        if not _redis_fallback_logged:
            logger.warning(
                "Redis unavailable for rate limiting (%s); using in-memory fallback",
                exc,
            )
            _redis_fallback_logged = True
        return None


def _check_rate_limit_memory(identity: str, limit: int, window: float, now: float) -> tuple[bool, int]:
    with _lock:
        bucket = _hits[identity]
        while bucket and now - bucket[0] >= window:
            bucket.popleft()

        if len(bucket) >= limit:
            retry_after = int(window - (now - bucket[0])) + 1
            return False, max(retry_after, 1)

        bucket.append(now)
        return True, 0


def _check_rate_limit_redis(
    client,
    identity: str,
    limit: int,
    window: float,
    now: float,
) -> tuple[bool, int]:
    key = f"{_RATE_LIMIT_KEY_PREFIX}{identity}"
    window_start = now - window

    client.zremrangebyscore(key, 0, window_start)
    count = client.zcard(key)

    if count >= limit:
        oldest = client.zrange(key, 0, 0, withscores=True)
        if oldest:
            retry_after = int(window - (now - oldest[0][1])) + 1
            return False, max(retry_after, 1)
        return False, 1

    client.zadd(key, {f"{now}:{uuid.uuid4().hex}": now})
    client.expire(key, int(window) + 1)
    return True, 0


def check_rate_limit(identity: str) -> tuple[bool, int]:
    """Sliding-window limiter. Returns (allowed, retry_after_seconds)."""
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return True, 0

    limit = max(1, settings.rate_limit_per_min)
    window = 60.0
    now = time.time()

    client = _get_redis_client()
    if client is not None:
        try:
            return _check_rate_limit_redis(client, identity, limit, window, now)
        except Exception as exc:
            global _redis_fallback_logged
            if not _redis_fallback_logged:
                logger.warning(
                    "Redis rate-limit operation failed (%s); using in-memory fallback",
                    exc,
                )
                _redis_fallback_logged = True

    return _check_rate_limit_memory(identity, limit, window, now)


def reset_rate_limits() -> None:
    """Clear all counters (used in tests)."""
    global _redis_client, _redis_fallback_logged

    with _lock:
        _hits.clear()

    client = _redis_client
    if client is not None:
        try:
            for key in client.scan_iter(f"{_RATE_LIMIT_KEY_PREFIX}*"):
                client.delete(key)
        except Exception:
            pass

    _redis_client = None
    _redis_fallback_logged = False
