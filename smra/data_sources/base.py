"""Abstract data-source interface for market data providers."""
from abc import ABC, abstractmethod
from datetime import date


class DataSource(ABC):
    """Fetch daily OHLCV bars and static fundamentals for a ticker."""

    @abstractmethod
    def fetch_daily_bar(self, ticker: str, bar_date: date) -> dict:
        """Return {symbol, date, open, high, low, close, volume} or {} if unavailable."""

    @abstractmethod
    def fetch_fundamentals(self, ticker: str) -> dict:
        """Return {company, sector, marketcap} — marketcap in billions (native currency)."""
