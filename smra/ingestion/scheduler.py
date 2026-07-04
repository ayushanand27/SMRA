"""APScheduler job: fetch live bars via yfinance and upsert into Postgres."""
import logging
import time
from datetime import date, datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

try:
    from smra.config.tickers import TICKERS
    from smra.data_sources.yfinance_source import YFinanceSource
    from smra.ingestion.upsert import upsert_daily_bars
    from smra.utils.config import get_settings
    from smra.utils.currency import currency_for_symbol
    from smra.utils.db import is_postgres, log_backend_status
except (ModuleNotFoundError, ImportError):
    from config.tickers import TICKERS
    from data_sources.yfinance_source import YFinanceSource
    from ingestion.upsert import upsert_daily_bars
    from utils.config import get_settings
    from utils.currency import currency_for_symbol
    from utils.db import is_postgres, log_backend_status

logger = logging.getLogger("smra.ingestion.scheduler")

_scheduler: BackgroundScheduler | None = None
_source = YFinanceSource()


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


def _fetch_ticker_with_retry(ticker: str, bar_date: date, max_attempts: int = 3) -> dict | None:
    """Fetch bar + fundamentals with exponential backoff (yfinance rate limits)."""
    fundamentals = {}
    for attempt in range(1, max_attempts + 1):
        try:
            bar = _source.fetch_daily_bar(ticker, bar_date)
            if not fundamentals:
                fundamentals = _source.fetch_fundamentals(ticker)
            if bar:
                bar["company"] = fundamentals.get("company")
                bar["sector"] = fundamentals.get("sector")
                bar["marketcap"] = fundamentals.get("marketcap")
                bar["currency"] = currency_for_symbol(bar.get("symbol", ticker))
                return bar
            return None
        except Exception:
            logger.exception("Fetch failed for %s (attempt %s/%s)", ticker, attempt, max_attempts)
            if attempt < max_attempts:
                time.sleep(2 ** (attempt - 1))
    return None


def run_ingestion_job(tickers: list[str] | None = None) -> dict:
    """Fetch and upsert daily bars for all configured tickers."""
    if not is_postgres():
        log_backend_status()
        logger.warning("Ingestion skipped: DATABASE_URL not set (Postgres required)")
        return {"ok": False, "reason": "postgres_required"}

    settings = get_settings()
    if not settings.ingestion_enabled:
        return {"ok": False, "reason": "disabled"}

    symbols = tickers or TICKERS
    bar_date = _today_utc()
    rows: list[dict] = []
    errors: list[str] = []

    logger.info("Ingestion run for %s ticker(s) on %s", len(symbols), bar_date)
    for ticker in symbols:
        try:
            row = _fetch_ticker_with_retry(ticker, bar_date)
            if row:
                rows.append(row)
            else:
                logger.info("No bar returned for %s on %s", ticker, bar_date)
        except Exception as exc:
            msg = f"{ticker}: {exc}"
            errors.append(msg)
            logger.exception("Unhandled error ingesting %s", ticker)

    upserted = 0
    if rows:
        upserted = upsert_daily_bars(rows)

    return {"ok": True, "date": str(bar_date), "fetched": len(rows), "upserted": upserted, "errors": errors}


def start_scheduler() -> BackgroundScheduler | None:
    """Start background ingestion scheduler (FastAPI startup)."""
    global _scheduler
    log_backend_status()
    settings = get_settings()
    if not settings.ingestion_enabled:
        logger.info("Ingestion scheduler disabled (INGESTION_ENABLED=0)")
        return None
    if not is_postgres():
        logger.info("Ingestion scheduler not started (Postgres DATABASE_URL required)")
        return None
    if _scheduler is not None:
        return _scheduler

    interval = max(1, settings.ingestion_interval_min)
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        run_ingestion_job,
        trigger="interval",
        minutes=interval,
        id="smra_live_ingestion",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    _scheduler.start()
    logger.info("Ingestion scheduler started (every %s min)", interval)
    return _scheduler


def stop_scheduler() -> None:
    """Shut down scheduler (FastAPI shutdown)."""
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        logger.info("Ingestion scheduler stopped")
        _scheduler = None
