"""Deterministic financial calculations — computed in pure Python, never by the LLM.

Industry-standard practice for AI finance tools (see e.g. FinRobot's design): valuation
and statistical figures come from code with full provenance; the LLM narrates them, it
never does the arithmetic itself. Letting an LLM "eyeball" a printed table and state a
moving average or % return is exactly the kind of thing that produces confidently wrong
numbers. Mirrors the pattern already used by smra.utils.currency.build_synthesis_notes:
inspect the question + result frame, hand the synthesis LLM computed facts to narrate.
"""
from __future__ import annotations

import math
import re

import pandas as pd

_MOVING_AVG_RE = re.compile(r"(\d+)[\s-]*day\s+(?:moving\s+average|ma\b|sma\b)", re.I)


def simple_return(df: pd.DataFrame, price_col: str = "close") -> float | None:
    """% change from the first to the last row. df must already be sorted by date."""
    if df.empty or price_col not in df.columns or len(df) < 2:
        return None
    first, last = df[price_col].iloc[0], df[price_col].iloc[-1]
    if not first:
        return None
    return round((last - first) / first * 100, 2)


def cagr(df: pd.DataFrame, date_col: str = "date", price_col: str = "close") -> float | None:
    """Compound annual growth rate between the first and last row."""
    if df.empty or len(df) < 2 or price_col not in df.columns or date_col not in df.columns:
        return None
    dates = pd.to_datetime(df[date_col])
    years = (dates.iloc[-1] - dates.iloc[0]).days / 365.25
    first, last = df[price_col].iloc[0], df[price_col].iloc[-1]
    if years <= 0 or not first or first <= 0:
        return None
    return round(((last / first) ** (1 / years) - 1) * 100, 2)


def moving_average(df: pd.DataFrame, window: int, price_col: str = "close") -> float | None:
    """Simple moving average of the most recent `window` rows (df sorted ascending by date)."""
    if df.empty or price_col not in df.columns:
        return None
    tail = df[price_col].tail(window)
    if tail.empty:
        return None
    return round(float(tail.mean()), 2)


def volatility(df: pd.DataFrame, price_col: str = "close") -> float | None:
    """Annualized volatility (%) from the standard deviation of daily returns."""
    if df.empty or price_col not in df.columns or len(df) < 3:
        return None
    returns = df[price_col].pct_change().dropna()
    if returns.empty:
        return None
    return round(float(returns.std() * math.sqrt(252) * 100), 2)


def high_low(df: pd.DataFrame, price_col: str = "close") -> tuple[float, float] | None:
    if df.empty or price_col not in df.columns:
        return None
    return round(float(df[price_col].max()), 2), round(float(df[price_col].min()), 2)


def _wants_moving_average(question: str) -> int | None:
    q = question.lower()
    match = _MOVING_AVG_RE.search(q)
    if match:
        return int(match.group(1))
    if "moving average" in q or re.search(r"\bma\b", q) or re.search(r"\bsma\b", q):
        return 20  # standard default window when the user doesn't specify one
    return None


def _wants_return(question: str) -> bool:
    q = question.lower()
    return any(k in q for k in ("% change", "percent change", "percentage change", "return", "gain", "loss"))


def _wants_cagr(question: str) -> bool:
    q = question.lower()
    return "cagr" in q or "annualized return" in q or "annual growth rate" in q


def _wants_volatility(question: str) -> bool:
    q = question.lower()
    return "volatility" in q or "std dev" in q or "standard deviation" in q or "how volatile" in q


def _wants_high_low(question: str) -> bool:
    q = question.lower()
    return ("52" in q and ("high" in q or "low" in q)) or ("highest" in q and "lowest" in q)


def _symbol_groups(df: pd.DataFrame) -> list[tuple[str, pd.DataFrame]]:
    """Split into (label, sub_df) pairs per symbol when the result spans more than one —
    averaging close prices across different stocks would silently produce a meaningless number.
    """
    if "symbol" not in df.columns or df["symbol"].nunique() <= 1:
        return [("", df)]
    return [(str(sym), sub) for sym, sub in df.groupby("symbol", sort=False)]


def build_calc_notes(user_question: str, df: pd.DataFrame) -> str:
    """Compute whatever deterministic metrics the question implies and hand them to the
    synthesis LLM as ground truth to narrate. Returns "" if nothing supported applies —
    the caller should fall back to letting the LLM synthesize from the raw preview as before.
    """
    if df.empty or "close" not in df.columns:
        return ""

    ordered = df.copy()
    if "date" in ordered.columns:
        ordered = ordered.sort_values("date")

    window = _wants_moving_average(user_question)
    want_return = _wants_return(user_question)
    want_cagr = _wants_cagr(user_question)
    want_vol = _wants_volatility(user_question)
    want_hl = _wants_high_low(user_question)

    if not any([window, want_return, want_cagr, want_vol, want_hl]):
        return ""

    notes: list[str] = []
    for label, sub in _symbol_groups(ordered):
        prefix = f"{label}: " if label else ""

        if window is not None:
            ma = moving_average(sub, window=window)
            if ma is not None:
                coverage = "" if len(sub) >= window else f" (only {len(sub)} rows available, fewer than {window})"
                notes.append(
                    f"COMPUTED (Python, not LLM): {prefix}{window}-day simple moving average of close "
                    f"= {ma}{coverage}. State this exact figure; do not estimate or recompute it yourself."
                )

        if want_return:
            ret = simple_return(sub)
            if ret is not None:
                notes.append(
                    f"COMPUTED (Python, not LLM): {prefix}% change from first to last row in the result "
                    f"= {ret}%. State this exact figure; do not estimate or recompute it yourself."
                )

        if want_cagr:
            rate = cagr(sub)
            if rate is not None:
                notes.append(
                    f"COMPUTED (Python, not LLM): {prefix}CAGR across the result's date range = {rate}%. "
                    f"State this exact figure; do not estimate or recompute it yourself."
                )

        if want_vol:
            vol = volatility(sub)
            if vol is not None:
                notes.append(
                    f"COMPUTED (Python, not LLM): {prefix}annualized volatility (stdev of daily returns) "
                    f"= {vol}%. State this exact figure; do not estimate or recompute it yourself."
                )

        if want_hl:
            hl = high_low(sub)
            if hl is not None:
                notes.append(
                    f"COMPUTED (Python, not LLM): {prefix}highest close in result = {hl[0]}, lowest close "
                    f"= {hl[1]}. State these exact figures; do not estimate or recompute them yourself."
                )

    return "\n".join(notes)
