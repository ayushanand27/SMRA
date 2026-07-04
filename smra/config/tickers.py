"""Tracked tickers for scheduled live ingestion.

US symbols are plain tickers (NYSE/NASDAQ). Indian symbols use the NSE ``.NS`` suffix
as required by yfinance (e.g. RELIANCE.NS). Prices and market cap are stored in each
symbol's native currency (USD vs INR) — see SQL agent schema notes.
"""
US_TICKERS: list[str] = [
    "AAPL",
    "ABBV",
    "AMZN",
    "BAC",
    "CL",
    "COP",
    "COST",
    "CVX",
    "EOG",
    "GOOGL",
    "GS",
    "HD",
    "JNJ",
    "JPM",
    "KO",
    "MA",
    "MCD",
    "META",
    "MRK",
    "MSFT",
    "NKE",
    "NVDA",
    "PFE",
    "PG",
    "SLB",
    "TSLA",
    "UNH",
    "V",
    "WMT",
    "XOM",
]

# Top NSE large-caps by market cap (yfinance suffix .NS)
IN_TICKERS: list[str] = [
    "RELIANCE.NS",
    "TCS.NS",
    "HDFCBANK.NS",
    "INFY.NS",
    "ICICIBANK.NS",
    "BHARTIARTL.NS",
    "SBIN.NS",
    "HINDUNILVR.NS",
    "ITC.NS",
    "LT.NS",
    "KOTAKBANK.NS",
    "AXISBANK.NS",
    "BAJFINANCE.NS",
    "MARUTI.NS",
    "SUNPHARMA.NS",
    "TITAN.NS",
    "HCLTECH.NS",
    "WIPRO.NS",
    "ULTRACEMCO.NS",
    "NTPC.NS",
]

TICKERS: list[str] = US_TICKERS + IN_TICKERS
