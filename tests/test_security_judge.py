"""Tests for API auth, rate limiting, and the LLM-judge parser."""
import importlib

import pytest

from smra.utils import security
from smra.utils.config import get_settings


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    # Force in-memory limiter unless a test explicitly enables Redis.
    monkeypatch.setenv("REDIS_URL", "memory")
    security.reset_rate_limits()
    # Reset settings cache-free (get_settings builds fresh each call).
    yield
    security.reset_rate_limits()


class TestApiKeyAuth:
    def test_auth_disabled_allows_all(self, monkeypatch):
        monkeypatch.delenv("AUTH_ENABLED", raising=False)
        assert security.verify_api_key(None) is True

    def test_auth_enabled_no_keys_fails_closed(self, monkeypatch):
        monkeypatch.setenv("AUTH_ENABLED", "1")
        monkeypatch.setenv("SMRA_API_KEYS", "")
        assert security.verify_api_key("anything") is False

    def test_auth_enabled_valid_key(self, monkeypatch):
        monkeypatch.setenv("AUTH_ENABLED", "1")
        monkeypatch.setenv("SMRA_API_KEYS", "key-a,key-b")
        assert security.verify_api_key("key-b") is True

    def test_auth_enabled_invalid_key(self, monkeypatch):
        monkeypatch.setenv("AUTH_ENABLED", "1")
        monkeypatch.setenv("SMRA_API_KEYS", "key-a,key-b")
        assert security.verify_api_key("nope") is False


class TestRateLimit:
    def test_within_limit_allowed(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
        monkeypatch.setenv("RATE_LIMIT_PER_MIN", "3")
        for _ in range(3):
            allowed, _ = security.check_rate_limit("id1")
            assert allowed is True

    def test_over_limit_blocked(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
        monkeypatch.setenv("RATE_LIMIT_PER_MIN", "2")
        security.check_rate_limit("id2")
        security.check_rate_limit("id2")
        allowed, retry_after = security.check_rate_limit("id2")
        assert allowed is False
        assert retry_after >= 1

    def test_disabled_never_blocks(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "0")
        monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
        for _ in range(10):
            allowed, _ = security.check_rate_limit("id3")
            assert allowed is True

    def test_identities_isolated(self, monkeypatch):
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
        monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
        assert security.check_rate_limit("a")[0] is True
        assert security.check_rate_limit("b")[0] is True
        assert security.check_rate_limit("a")[0] is False


class TestRateLimitRedis:
    class _FakeRedis:
        """Minimal sorted-set stub for Redis sliding-window tests."""

        def __init__(self):
            self._zsets: dict[str, dict[str, float]] = {}

        def ping(self):
            return True

        def zremrangebyscore(self, key, min_score, max_score):
            zset = self._zsets.setdefault(key, {})
            self._zsets[key] = {
                member: score
                for member, score in zset.items()
                if not (min_score <= score <= max_score)
            }

        def zcard(self, key):
            return len(self._zsets.get(key, {}))

        def zrange(self, key, start, end, withscores=False):
            items = sorted(self._zsets.get(key, {}).items(), key=lambda kv: kv[1])
            if end == -1:
                end = len(items) - 1
            sliced = items[start : end + 1]
            if withscores:
                return sliced
            return [member for member, _ in sliced]

        def zadd(self, key, mapping):
            zset = self._zsets.setdefault(key, {})
            zset.update({str(member): float(score) for member, score in mapping.items()})

        def expire(self, key, ttl):
            return True

        def scan_iter(self, match):
            prefix = match.rstrip("*")
            for key in list(self._zsets.keys()):
                if key.startswith(prefix):
                    yield key

        def delete(self, key):
            self._zsets.pop(key, None)

    def test_redis_backend_enforces_limit(self, monkeypatch):
        fake = self._FakeRedis()
        monkeypatch.setenv("REDIS_URL", "redis://localhost:6379")
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
        monkeypatch.setenv("RATE_LIMIT_PER_MIN", "2")
        monkeypatch.setattr(security, "_get_redis_client", lambda: fake)

        assert security.check_rate_limit("redis-id")[0] is True
        assert security.check_rate_limit("redis-id")[0] is True
        allowed, retry_after = security.check_rate_limit("redis-id")
        assert allowed is False
        assert retry_after >= 1

    def test_redis_unreachable_falls_back_to_memory(self, monkeypatch, caplog):
        monkeypatch.setenv("REDIS_URL", "redis://127.0.0.1:59999")
        monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
        monkeypatch.setenv("RATE_LIMIT_PER_MIN", "1")
        security.reset_rate_limits()

        with caplog.at_level("WARNING"):
            assert security.check_rate_limit("fallback-id")[0] is True
            assert security.check_rate_limit("fallback-id")[0] is False

        assert any("in-memory fallback" in rec.message.lower() for rec in caplog.records)


class TestSettingsParsing:
    def test_api_keys_parsed_and_trimmed(self, monkeypatch):
        monkeypatch.setenv("SMRA_API_KEYS", " k1 , k2 ,, k3 ")
        assert get_settings().api_keys == ["k1", "k2", "k3"]


class TestJudgeParser:
    def _judge_with(self, monkeypatch, raw):
        judge_mod = importlib.import_module("smra.eval.judge")
        monkeypatch.setattr(judge_mod, "call_llm", lambda *a, **k: raw)
        return judge_mod.judge_answer("What is AAPL revenue?", "AAPL revenue was $383B in FY2023.")

    def test_empty_answer_scores_zero(self):
        from smra.eval.judge import judge_answer

        result = judge_answer("q", "")
        assert result.score == 0.0

    def test_parses_clean_json(self, monkeypatch):
        raw = '{"relevance": 5, "groundedness": 4, "clarity": 5, "rationale": "good"}'
        result = self._judge_with(monkeypatch, raw)
        assert result.relevance == 5
        assert result.score == pytest.approx((5 + 4 + 5) / 15.0, abs=0.01)

    def test_parses_fenced_json(self, monkeypatch):
        raw = '```json\n{"relevance": 3, "groundedness": 3, "clarity": 3}\n```'
        result = self._judge_with(monkeypatch, raw)
        assert result.score == pytest.approx(9 / 15.0, abs=0.01)

    def test_clamps_out_of_range(self, monkeypatch):
        raw = '{"relevance": 9, "groundedness": 0, "clarity": 5}'
        result = self._judge_with(monkeypatch, raw)
        assert result.relevance == 5
        assert result.groundedness == 1

    def test_unparseable_scores_zero(self, monkeypatch):
        result = self._judge_with(monkeypatch, "the answer is great")
        assert result.score == 0.0
