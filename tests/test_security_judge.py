"""Tests for API auth, rate limiting, and the LLM-judge parser."""
import importlib

import pytest

from smra.utils import security
from smra.utils.config import get_settings


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
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
