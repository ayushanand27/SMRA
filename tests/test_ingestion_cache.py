"""Tests for TTL cache and ingestion helpers."""
from unittest.mock import patch

import pandas as pd

from smra.cache.ttl_cache import InMemoryTTLCache, cached_read_sql, reset_query_cache
from smra.data_sources.yfinance_source import YFinanceSource, _normalize_ticker


class TestTTLCache:
    def setup_method(self):
        reset_query_cache()

    def test_set_and_get(self):
        cache = InMemoryTTLCache(ttl_seconds=60)
        cache.set("k", {"a": 1})
        assert cache.get("k") == {"a": 1}

    def test_expired_entry(self):
        cache = InMemoryTTLCache(ttl_seconds=1)
        cache.set("k", "v")
        cache._store["k"] = (0.0, "v")  # force expiry
        assert cache.get("k") is None

    def test_cached_read_sql_hits_fn_once(self, monkeypatch):
        reset_query_cache()
        monkeypatch.setenv("QUERY_CACHE_ENABLED", "1")
        monkeypatch.setenv("CACHE_TTL_SECONDS", "300")
        calls = {"n": 0}

        def fake_read(sql, params=None):
            calls["n"] += 1
            return pd.DataFrame({"x": [1]})

        out1 = cached_read_sql(fake_read, "SELECT 1", {})
        out2 = cached_read_sql(fake_read, "SELECT 1", {})
        assert calls["n"] == 1
        assert len(out1) == len(out2) == 1


class TestYFinanceSource:
    def test_normalize_plain_ticker(self):
        assert _normalize_ticker("aapl") == "AAPL"

    def test_normalize_ns_suffix(self):
        assert _normalize_ticker("reliance.ns") == "RELIANCE.NS"

    @patch("smra.data_sources.yfinance_source.yf.Ticker")
    def test_fetch_daily_bar(self, mock_ticker_cls):
        mock_hist = pd.DataFrame(
            {"Open": [1.0], "High": [2.0], "Low": [0.5], "Close": [1.5], "Volume": [1000]},
            index=pd.to_datetime(["2025-06-01"]),
        )
        mock_ticker_cls.return_value.history.return_value = mock_hist
        src = YFinanceSource()
        bar = src.fetch_daily_bar("AAPL", pd.Timestamp("2025-06-01").date())
        assert bar["symbol"] == "AAPL"
        assert bar["close"] == 1.5
        assert bar["volume"] == 1000
