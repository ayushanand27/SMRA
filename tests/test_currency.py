"""Tests for multi-market currency helpers."""
import pandas as pd

from smra.utils.currency import (
    build_synthesis_notes,
    currency_for_symbol,
    enrich_dataframe_currency,
    has_mixed_currencies,
    is_marketcap_ranking_question,
)


def test_currency_for_us_symbol():
    assert currency_for_symbol("AAPL") == "USD"
    assert currency_for_symbol("nvda") == "USD"


def test_currency_for_nse_symbol():
    assert currency_for_symbol("RELIANCE.NS") == "INR"
    assert currency_for_symbol("tcs.ns") == "INR"


def test_enrich_adds_currency_column():
    df = pd.DataFrame({"symbol": ["AAPL", "RELIANCE.NS"], "close": [100.0, 1300.0]})
    out = enrich_dataframe_currency(df)
    assert list(out["currency"]) == ["USD", "INR"]


def test_mixed_currencies_detected():
    df = enrich_dataframe_currency(
        pd.DataFrame({"symbol": ["AAPL", "RELIANCE.NS"], "marketcap": [3000, 17000]})
    )
    assert has_mixed_currencies(df) is True


def test_marketcap_ranking_question():
    assert is_marketcap_ranking_question("top 5 stocks by marketcap") is True
    assert is_marketcap_ranking_question("AAPL closing price yesterday") is False


def test_synthesis_notes_warn_on_mixed_marketcap_rank():
    df = enrich_dataframe_currency(
        pd.DataFrame(
            {
                "symbol": ["AAPL", "RELIANCE.NS"],
                "company": ["Apple", "Reliance"],
                "marketcap": [3000, 17646],
                "currency": ["USD", "INR"],
            }
        )
    )
    notes = build_synthesis_notes("top 5 stocks by marketcap", df)
    assert "NOT directly comparable" in notes
    assert "INR" in notes
