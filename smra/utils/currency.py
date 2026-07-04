"""Currency helpers for multi-market stock_prices (US USD, NSE INR)."""
from __future__ import annotations

import pandas as pd

VALID_CURRENCIES = frozenset({"USD", "INR"})


def currency_for_symbol(symbol: str) -> str:
    """Return ISO-like currency code from ticker symbol."""
    if not symbol:
        return "USD"
    return "INR" if str(symbol).upper().endswith(".NS") else "USD"


def currency_symbol(code: str) -> str:
    """Display symbol for synthesis prompts."""
    return "₹" if code == "INR" else "$"


def enrich_dataframe_currency(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure a currency column exists; infer from symbol when missing."""
    if df.empty or "symbol" not in df.columns:
        return df
    out = df.copy()
    if "currency" not in out.columns:
        out["currency"] = out["symbol"].map(currency_for_symbol)
    else:
        missing = out["currency"].isna() | (out["currency"].astype(str).str.strip() == "")
        if missing.any():
            out.loc[missing, "currency"] = out.loc[missing, "symbol"].map(currency_for_symbol)
    return out


def currencies_in_frame(df: pd.DataFrame) -> set[str]:
    """Distinct currency codes present in the frame."""
    if df.empty or "currency" not in df.columns:
        return set()
    return {str(c).upper() for c in df["currency"].dropna().unique() if str(c).upper() in VALID_CURRENCIES}


def has_mixed_currencies(df: pd.DataFrame) -> bool:
    return len(currencies_in_frame(df)) > 1


def is_marketcap_ranking_question(question: str) -> bool:
    q = question.lower()
    if "marketcap" not in q and "market cap" not in q and "market-cap" not in q:
        return False
    return any(k in q for k in ("top", "highest", "largest", "biggest", "rank", "compare", "most valuable"))


def build_synthesis_notes(user_question: str, df: pd.DataFrame) -> str:
    """Extra instructions for the synthesis LLM based on result shape."""
    notes: list[str] = []
    enriched = enrich_dataframe_currency(df)
    currencies = sorted(currencies_in_frame(enriched))

    if currencies:
        notes.append(
            "Per-row currency codes in result: "
            + ", ".join(f"{currency_symbol(c)} / {c}" for c in currencies)
            + ". Label each amount using the currency column only (do not infer from symbol suffix)."
        )

    if has_mixed_currencies(enriched):
        notes.append(
            "WARNING: Result mixes USD and INR rows. Marketcap and price values are NOT directly "
            "comparable across currencies. State this explicitly. Do not rank them as if comparable "
            "unless the user filtered to one currency."
        )

    if is_marketcap_ranking_question(user_question) and has_mixed_currencies(enriched):
        notes.append(
            "This is a cross-market marketcap ranking — emphasize that the ordering mixes unlike units "
            "or suggest filtering to USD-only or INR-only for a fair comparison."
        )

    return "\n".join(notes)
