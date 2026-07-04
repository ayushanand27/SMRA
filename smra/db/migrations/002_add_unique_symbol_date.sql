-- Migration 002: unique (symbol, date) for safe ON CONFLICT upserts during live ingestion.
-- Pre-check: SELECT symbol, date, COUNT(*) FROM stock_prices GROUP BY 1,2 HAVING COUNT(*)>1;
-- Result on 2026-07-04: zero duplicates across 7,560 rows.

CREATE UNIQUE INDEX IF NOT EXISTS uq_stock_prices_symbol_date
    ON stock_prices (symbol, date);
