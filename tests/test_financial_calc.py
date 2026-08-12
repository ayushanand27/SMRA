"""Tests for deterministic financial calculations (never left to the LLM)."""
import pandas as pd

from smra.utils.financial_calc import (
    build_calc_notes,
    cagr,
    high_low,
    moving_average,
    simple_return,
    volatility,
)


def _price_series(closes: list[float], start: str = "2025-01-01") -> pd.DataFrame:
    dates = pd.date_range(start, periods=len(closes), freq="D").strftime("%Y-%m-%d")
    return pd.DataFrame({"symbol": "AAPL", "date": dates, "close": closes})


def test_simple_return_computes_percent_change():
    df = _price_series([100.0, 110.0])
    assert simple_return(df) == 10.0


def test_simple_return_none_with_fewer_than_two_rows():
    assert simple_return(_price_series([100.0])) is None
    assert simple_return(pd.DataFrame({"close": []})) is None


def test_cagr_matches_formula_over_roughly_two_years():
    df = _price_series([100.0, 121.0], start="2023-01-01")
    df.loc[1, "date"] = "2025-01-01"  # ~2 years later
    rate = cagr(df)
    dates = pd.to_datetime(df["date"])
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    expected = round(((121.0 / 100.0) ** (1 / years) - 1) * 100, 2)
    assert rate == expected
    assert 9.9 < rate < 10.1  # sanity: ~10% given ~2 years and a 21% total gain


def test_moving_average_uses_only_most_recent_window():
    df = _price_series([10.0, 20.0, 30.0, 40.0, 50.0])
    assert moving_average(df, window=2) == 45.0  # mean of last two: 40, 50
    assert moving_average(df, window=5) == 30.0  # mean of all five


def test_moving_average_degrades_gracefully_with_insufficient_rows():
    df = _price_series([10.0, 20.0])
    assert moving_average(df, window=20) == 15.0  # averages what's available, doesn't error


def test_volatility_is_zero_for_constant_prices():
    df = _price_series([100.0] * 10)
    assert volatility(df) == 0.0


def test_volatility_none_with_too_few_rows():
    assert volatility(_price_series([100.0, 101.0])) is None


def test_high_low_returns_max_and_min():
    df = _price_series([100.0, 150.0, 80.0, 120.0])
    assert high_low(df) == (150.0, 80.0)


def test_build_calc_notes_empty_when_question_has_no_calc_intent():
    df = _price_series([100.0, 110.0])
    assert build_calc_notes("What was AAPL closing price?", df) == ""


def test_build_calc_notes_empty_on_empty_dataframe():
    assert build_calc_notes("20 day moving average of AAPL", pd.DataFrame()) == ""


def test_build_calc_notes_moving_average_with_explicit_window():
    df = _price_series([float(i) for i in range(1, 51)])  # 1..50
    notes = build_calc_notes("What is the 20 day moving average for AAPL?", df)
    assert "COMPUTED (Python, not LLM)" in notes
    assert "20-day simple moving average" in notes
    # mean of the last 20 values (31..50) = 40.5
    assert "40.5" in notes


def test_build_calc_notes_default_window_when_unspecified():
    df = _price_series([float(i) for i in range(1, 51)])
    notes = build_calc_notes("What's the moving average for AAPL?", df)
    assert "20-day simple moving average" in notes


def test_build_calc_notes_return_intent():
    df = _price_series([100.0, 150.0])
    notes = build_calc_notes("What was the % change for AAPL this period?", df)
    assert "% change from first to last row in the result = 50.0%" in notes


def test_build_calc_notes_volatility_intent():
    df = _price_series([100.0] * 10)
    notes = build_calc_notes("How volatile has AAPL been?", df)
    assert "annualized volatility" in notes
    assert "= 0.0%" in notes


def test_build_calc_notes_high_low_intent():
    df = _price_series([100.0, 150.0, 80.0])
    notes = build_calc_notes("What is the 52 week high and low for AAPL?", df)
    assert "highest close in result = 150.0, lowest close = 80.0" in notes


def test_build_calc_notes_computes_per_symbol_when_result_has_multiple_symbols():
    aapl = _price_series([100.0, 200.0])
    nvda = _price_series([50.0, 40.0])
    nvda["symbol"] = "NVDA"
    df = pd.concat([aapl, nvda], ignore_index=True)

    notes = build_calc_notes("What was the % change for AAPL and NVDA?", df)
    assert "AAPL: % change from first to last row in the result = 100.0%" in notes
    assert "NVDA: % change from first to last row in the result = -20.0%" in notes


def test_build_calc_notes_single_symbol_has_no_label_prefix():
    df = _price_series([100.0, 150.0])
    notes = build_calc_notes("What was the % change for AAPL?", df)
    assert "AAPL:" not in notes
    assert notes.startswith("COMPUTED (Python, not LLM): % change")
