"""yfinance-backed market data source."""
import logging
from datetime import date, datetime, timedelta
from typing import Any

import yfinance as yf

from smra.data_sources.base import DataSource

logger = logging.getLogger("smra.yfinance")


def _normalize_ticker(ticker: str) -> str:
    """Preserve exchange suffixes (e.g. RELIANCE.NS); uppercase plain tickers."""
    t = ticker.strip()
    if "." in t:
        base, suffix = t.split(".", 1)
        return f"{base.upper()}.{suffix.upper()}"
    return t.upper()


class YFinanceSource(DataSource):
    """Fetch bars and fundamentals via yfinance (AAPL, RELIANCE.NS, etc.)."""

    def fetch_daily_bar(self, ticker: str, bar_date: date) -> dict:
        symbol = _normalize_ticker(ticker)
        end = bar_date + timedelta(days=1)
        try:
            hist = yf.Ticker(symbol).history(
                start=bar_date.isoformat(),
                end=end.isoformat(),
                auto_adjust=False,
            )
        except Exception:
            logger.exception("yfinance history failed for %s on %s", symbol, bar_date)
            return {}

        if hist is None or hist.empty:
            return {}

        row = hist.iloc[-1]
        ts = hist.index[-1]
        if hasattr(ts, "to_pydatetime"):
            ts = ts.to_pydatetime()
        if isinstance(ts, datetime):
            bar_ts = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            bar_ts = datetime.combine(bar_date, datetime.min.time())

        return {
            "symbol": symbol,
            "date": bar_ts,
            "open": float(row.get("Open", 0) or 0),
            "high": float(row.get("High", 0) or 0),
            "low": float(row.get("Low", 0) or 0),
            "close": float(row.get("Close", 0) or 0),
            "volume": int(row.get("Volume", 0) or 0),
        }

    def fetch_fundamentals(self, ticker: str) -> dict:
        symbol = _normalize_ticker(ticker)
        try:
            info: dict[str, Any] = yf.Ticker(symbol).info or {}
        except Exception:
            logger.exception("yfinance info failed for %s", symbol)
            return {"company": None, "sector": None, "marketcap": None}

        company = info.get("longName") or info.get("shortName") or symbol
        sector = info.get("sector")
        raw_cap = info.get("marketCap")
        marketcap = round(float(raw_cap) / 1_000_000_000, 4) if raw_cap else None
        return {"company": company, "sector": sector, "marketcap": marketcap}
