"""Semantic + exact-match answer cache for repeated user queries (opt-in)."""
from __future__ import annotations

import logging
import math
import re
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("smra.cache.semantic")

_EMBED_DIM = 384
_embeddings = None
_embed_mode: str | None = None  # "hf" | "fallback"
_lock = threading.Lock()
_exact_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_semantic_entries: list[tuple[float, list[float], dict[str, Any]]] = []


def _normalize_query(query: str) -> str:
    return " ".join(query.lower().split())


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9]+", _normalize_query(text))


def _get_settings():
    try:
        from smra.utils.config import get_settings
    except (ModuleNotFoundError, ImportError):
        from utils.config import get_settings
    return get_settings()


def _fallback_embed(text: str, dim: int = _EMBED_DIM) -> list[float]:
    """Deterministic hash bag-of-words embedding when HuggingFace is unavailable."""
    vec = [0.0] * dim
    for token in _tokenize(text):
        idx = hash(token) % dim
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    if norm == 0:
        return vec
    return [v / norm for v in vec]


def _load_hf_embeddings():
    from langchain_huggingface import HuggingFaceEmbeddings

    return HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        model_kwargs={"device": "cpu"},
        show_progress=False,
    )


def _get_embeddings():
    global _embeddings, _embed_mode
    if _embeddings is not None:
        return _embeddings
    try:
        _embeddings = _load_hf_embeddings()
        _embed_mode = "hf"
        logger.info("Semantic cache using HuggingFace embeddings")
    except Exception as exc:
        logger.warning("Semantic cache HF embeddings unavailable (%s); using fallback embedder", exc)
        _embeddings = _FallbackEmbedder()
        _embed_mode = "fallback"
    return _embeddings


class _FallbackEmbedder:
    """Minimal embedder API compatible with HuggingFaceEmbeddings."""

    def embed_query(self, text: str) -> list[float]:
        return _fallback_embed(text)


def _to_vector(raw: Any) -> list[float]:
    if raw is None:
        return []
    if hasattr(raw, "tolist"):
        return [float(x) for x in raw.tolist()]
    return [float(x) for x in raw]


def _embed_text(text: str) -> list[float]:
    emb = _get_embeddings()
    if emb is None:
        return _fallback_embed(text)
    try:
        return _to_vector(emb.embed_query(text))
    except Exception as exc:
        logger.warning("Semantic cache embed_query failed (%s); using fallback vector", exc)
        return _fallback_embed(text)


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _prune(now: float, ttl: int, max_entries: int) -> None:
    global _exact_cache, _semantic_entries
    _exact_cache = {k: v for k, v in _exact_cache.items() if v[0] > now}
    _semantic_entries = [e for e in _semantic_entries if e[0] > now]
    cap = max_entries if max_entries > 0 else len(_semantic_entries)
    if cap and len(_semantic_entries) > cap:
        _semantic_entries = _semantic_entries[-cap:]


def reset_semantic_cache() -> None:
    global _exact_cache, _semantic_entries, _embeddings, _embed_mode
    with _lock:
        _exact_cache.clear()
        _semantic_entries.clear()
        _embeddings = None
        _embed_mode = None


def get_cached_answer(query: str) -> Optional[dict[str, Any]]:
    """Return cached API payload if exact or semantic match hits."""
    settings = _get_settings()
    if not settings.semantic_cache_enabled:
        return None

    key = _normalize_query(query)
    now = time.time()
    ttl = settings.semantic_cache_ttl_seconds

    with _lock:
        _prune(now, ttl, settings.semantic_cache_max_entries)
        exact = _exact_cache.get(key)
        if exact and exact[0] > now:
            logger.info("Semantic cache exact hit")
            return dict(exact[1])

    qv = _embed_text(query)
    if not qv:
        return None

    best_score = 0.0
    best_payload: dict[str, Any] | None = None
    with _lock:
        for expires, vec, payload in _semantic_entries:
            if expires <= now:
                continue
            score = _cosine(qv, vec)
            if score > best_score:
                best_score = score
                best_payload = payload

    threshold = settings.semantic_cache_threshold
    if best_payload and best_score >= threshold:
        logger.info("Semantic cache similarity hit (score=%.3f, threshold=%.2f)", best_score, threshold)
        return dict(best_payload)

    if _semantic_entries:
        logger.debug(
            "Semantic cache miss (best_score=%.3f, threshold=%.2f, mode=%s)",
            best_score,
            threshold,
            _embed_mode,
        )
    return None


def set_cached_answer(query: str, payload: dict[str, Any]) -> None:
    settings = _get_settings()
    if not settings.semantic_cache_enabled:
        return
    if not (payload.get("answer") or "").strip():
        return

    key = _normalize_query(query)
    now = time.time()
    ttl = settings.semantic_cache_ttl_seconds
    expires = now + ttl
    stored = dict(payload)

    qv = _embed_text(query)
    if not qv:
        logger.warning("Semantic cache store skipped: empty embedding for query")
        return

    with _lock:
        _exact_cache[key] = (expires, stored)
        _semantic_entries.append((expires, qv, stored))
        _prune(now, ttl, settings.semantic_cache_max_entries)
