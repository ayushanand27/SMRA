-- Postgres 1:1 equivalent of smra/data/smra.db (stock_prices only)
-- Column names intentionally unchanged for the SQL agent prompt.

CREATE TABLE IF NOT EXISTS stock_prices (
    symbol    TEXT,
    company   TEXT,
    sector    TEXT,
    date      TIMESTAMP WITHOUT TIME ZONE,
    open      DOUBLE PRECISION,
    high      DOUBLE PRECISION,
    low       DOUBLE PRECISION,
    close     DOUBLE PRECISION,
    volume    BIGINT,
    marketcap DOUBLE PRECISION,
    currency  TEXT
);

CREATE INDEX IF NOT EXISTS idx_sym_date ON stock_prices (symbol, date DESC);
