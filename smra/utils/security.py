"""API authentication and rate limiting.

- API-key auth via the `X-API-Key` header (constant-time comparison).
- In-memory sliding-window rate limiter keyed by API key or client IP.

The rate limiter is process-local; for multi-instance deployments swap the
store for Redis. Both controls are config-gated so local dev stays frictionless.
"""
import hmac
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

try:
    from smra.utils.config import get_settings
except (ModuleNotFoundError, ImportError):
    from utils.config import get_settings

_lock = threading.Lock()
_hits: Dict[str, Deque[float]] = defaultdict(deque)


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


def check_rate_limit(identity: str) -> tuple[bool, int]:
    """Sliding-window limiter. Returns (allowed, retry_after_seconds)."""
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return True, 0

    limit = max(1, settings.rate_limit_per_min)
    window = 60.0
    now = time.time()

    with _lock:
        bucket = _hits[identity]
        while bucket and now - bucket[0] >= window:
            bucket.popleft()

        if len(bucket) >= limit:
            retry_after = int(window - (now - bucket[0])) + 1
            return False, max(retry_after, 1)

        bucket.append(now)
        return True, 0


def reset_rate_limits() -> None:
    """Clear all counters (used in tests)."""
    with _lock:
        _hits.clear()
