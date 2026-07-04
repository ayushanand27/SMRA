"""Tests for config-driven DB layer (SQLite fallback)."""
import pytest

from smra.utils.db import get_database_url, is_postgres, read_sql_query, reset_engine, scalar_query


@pytest.fixture(autouse=True)
def _clean_engine(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    reset_engine()
    yield
    reset_engine()


def test_sqlite_fallback_url():
    url = get_database_url()
    assert url.startswith("sqlite:///")
    assert is_postgres() is False


def test_sqlite_read_count():
    n = scalar_query("SELECT COUNT(*) FROM stock_prices")
    assert n == 7560


def test_sqlite_read_sample():
    df = read_sql_query(
        "SELECT symbol, close FROM stock_prices WHERE symbol = :sym ORDER BY date LIMIT 3",
        params={"sym": "AAPL"},
    )
    assert len(df) == 3
    assert "close" in df.columns
