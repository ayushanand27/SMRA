"""Tests for opt-in semantic answer cache."""
import pytest

from smra.cache.semantic_cache import get_cached_answer, reset_semantic_cache, set_cached_answer


@pytest.fixture
def semantic_cache_on(monkeypatch):
    """Enable semantic cache with deterministic settings (immune to shell/.env drift)."""
    monkeypatch.setenv("SEMANTIC_CACHE_ENABLED", "1")
    monkeypatch.setenv("SEMANTIC_CACHE_THRESHOLD", "0.80")
    monkeypatch.setenv("SEMANTIC_CACHE_TTL_SECONDS", "3600")
    monkeypatch.setenv("SEMANTIC_CACHE_MAX_ENTRIES", "200")
    reset_semantic_cache()
    yield
    reset_semantic_cache()


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("SEMANTIC_CACHE_ENABLED", raising=False)
    reset_semantic_cache()
    set_cached_answer("hello", {"answer": "world"})
    assert get_cached_answer("hello") is None


def test_exact_match_when_enabled(semantic_cache_on):
    payload = {"answer": "AAPL close was 100", "routes": ["SQL"]}
    set_cached_answer("What is AAPL close?", payload)
    hit = get_cached_answer("What is AAPL close?")
    assert hit is not None
    assert hit["answer"] == payload["answer"]


def test_semantic_match_similar_query(semantic_cache_on):
    """Realistic MiniLM paraphrase (~0.83 cosine) should hit at threshold 0.80."""
    base = {"answer": "Revenue was 100B", "routes": ["RAG"]}
    q1 = "What was Apple total net sales?"
    q2 = "Apple total net sales in 10-K"
    set_cached_answer(q1, base)
    hit = get_cached_answer(q2)
    assert hit is not None, "expected semantic cache hit for paraphrased query"
    assert hit["answer"] == base["answer"]


def test_semantic_similarity_score_realistic_for_miniLM(semantic_cache_on):
    from smra.cache.semantic_cache import _cosine, _embed_text

    q1 = "What was Apple total net sales?"
    q2 = "Apple total net sales in 10-K"
    score = _cosine(_embed_text(q1), _embed_text(q2))
    assert 0.80 <= score < 0.90, f"expected MiniLM paraphrase band, got {score:.3f}"


def test_no_match_different_topic(semantic_cache_on):
    from smra.cache.semantic_cache import _cosine, _embed_text

    set_cached_answer("Tesla vehicle deliveries", {"answer": "Tesla answer"})
    assert get_cached_answer("Microsoft Azure revenue filing") is None

    score = _cosine(
        _embed_text("Tesla vehicle deliveries"),
        _embed_text("Microsoft Azure revenue filing"),
    )
    assert score < 0.80, f"unrelated queries should not approach cache threshold, got {score:.3f}"
