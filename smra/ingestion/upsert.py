"""Batch upsert into stock_prices (Postgres ON CONFLICT).

Requires unique index uq_stock_prices_symbol_date — applied automatically on first run
via smra/db/migrations/002_add_unique_symbol_date.sql when duplicates are absent.
"""
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import text

try:
    from smra.utils.currency import currency_for_symbol
    from smra.utils.db import get_engine, is_postgres
except (ModuleNotFoundError, ImportError):
    from utils.currency import currency_for_symbol
    from utils.db import get_engine, is_postgres

logger = logging.getLogger("smra.ingestion.upsert")

_MIGRATION_002 = Path(__file__).resolve().parents[1] / "db" / "migrations" / "002_add_unique_symbol_date.sql"
_MIGRATION_003 = Path(__file__).resolve().parents[1] / "db" / "migrations" / "003_add_currency_column.sql"

UPSERT_SQL = text(
    """
    INSERT INTO stock_prices (
        symbol, company, sector, date, open, high, low, close, volume, marketcap, currency
    ) VALUES (
        :symbol, :company, :sector, :date, :open, :high, :low, :close, :volume, :marketcap, :currency
    )
    ON CONFLICT (symbol, date) DO UPDATE SET
        company   = EXCLUDED.company,
        sector    = EXCLUDED.sector,
        open      = EXCLUDED.open,
        high      = EXCLUDED.high,
        low       = EXCLUDED.low,
        close     = EXCLUDED.close,
        volume    = EXCLUDED.volume,
        marketcap = EXCLUDED.marketcap,
        currency  = EXCLUDED.currency
    """
)

_constraint_ready = False
_currency_ready = False


def ensure_unique_constraint() -> None:
    """Apply migration 002 if the unique (symbol, date) index is missing."""
    global _constraint_ready
    if _constraint_ready or not is_postgres():
        return

    engine = get_engine()
    with engine.begin() as conn:
        exists = conn.execute(
            text(
                "SELECT 1 FROM pg_indexes "
                "WHERE tablename = 'stock_prices' AND indexname = 'uq_stock_prices_symbol_date'"
            )
        ).fetchone()
        if exists:
            _constraint_ready = True
            return

        dupes = conn.execute(
            text(
                "SELECT COUNT(*) FROM ("
                "  SELECT symbol, date FROM stock_prices "
                "  GROUP BY symbol, date HAVING COUNT(*) > 1"
                ") d"
            )
        ).scalar()
        if dupes:
            raise RuntimeError(
                f"Cannot add unique (symbol, date): found {dupes} duplicate groups. Dedupe first."
            )

        logger.info("Applying migration 002: unique index on (symbol, date)")
        conn.execute(text(_MIGRATION_002.read_text(encoding="utf-8")))
    _constraint_ready = True


def ensure_currency_column() -> None:
    """Apply migration 003 and backfill currency from symbol suffix."""
    global _currency_ready
    if _currency_ready or not is_postgres():
        return

    engine = get_engine()
    with engine.begin() as conn:
        exists = conn.execute(
            text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'stock_prices' AND column_name = 'currency'"
            )
        ).fetchone()
        if not exists:
            logger.info("Applying migration 003: currency column on stock_prices")
            conn.execute(text(_MIGRATION_003.read_text(encoding="utf-8")))
    _currency_ready = True


def _with_currency(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["currency"] = item.get("currency") or currency_for_symbol(str(item.get("symbol", "")))
        out.append(item)
    return out


def upsert_daily_bars(rows: list[dict[str, Any]], batch_size: int = 200) -> int:
    """Upsert bar rows in batches. Returns number of rows processed."""
    if not rows:
        return 0
    if not is_postgres():
        raise RuntimeError("upsert_daily_bars requires Postgres (set DATABASE_URL)")

    ensure_unique_constraint()
    ensure_currency_column()
    engine = get_engine()
    total = 0
    prepared = _with_currency(rows)

    with engine.begin() as conn:
        for i in range(0, len(prepared), batch_size):
            chunk = prepared[i : i + batch_size]
            conn.execute(UPSERT_SQL, chunk)
            total += len(chunk)

    logger.info("Upserted %s bar row(s)", total)
    return total
