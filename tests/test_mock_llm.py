"""Tests for MOCK_MODE LLM stubs and SQL normalization."""


def test_mock_mode_off_by_default(monkeypatch):
    monkeypatch.delenv("MOCK_MODE", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    from smra.utils.config import is_mock_mode

    assert is_mock_mode() is False


def test_mock_mode_enabled_via_env(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "1")
    from smra.utils.config import is_mock_mode

    assert is_mock_mode() is True


def test_call_llm_mock_returns_router_json(monkeypatch):
    monkeypatch.setenv("MOCK_MODE", "1")
    from smra.utils.llm import call_llm

    raw = call_llm("You are a query router", "Query: What was AAPL close?")
    assert '"SQL"' in raw


def test_normalize_sql_takes_first_select_only():
    from smra.agents.sql_agent import _normalize_sql

    raw = (
        "SELECT close FROM stock_prices WHERE symbol = 'AAPL' ORDER BY date\n\n"
        "SELECT symbol, company FROM stock_prices GROUP BY symbol, company, sector"
    )
    sql = _normalize_sql(raw)
    assert sql.startswith("SELECT close")
    assert "GROUP BY" not in sql
