"""Copy stock_prices from SQLite (smra/data/smra.db) into Postgres.

Uses synchronous psycopg2 batch inserts (no pandas.to_sql on SQLAlchemy engine).

Usage (PowerShell) — set DATABASE_URL in smra/.env, then:
    python -m smra.scripts.migrate_sqlite_to_postgres --truncate

Or pass URL directly:
    python -m smra.scripts.migrate_sqlite_to_postgres --truncate `
        --database-url postgresql+psycopg2://postgres:smra@127.0.0.1:5434/smra
"""
import argparse
import os
import sys
import time
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from psycopg2.extras import execute_batch
from sqlalchemy import create_engine, text

from smra.utils.currency import currency_for_symbol

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_ENV = _ROOT / "smra" / ".env"
if _ENV.exists():
    load_dotenv(_ENV, override=True)

SCHEMA_SQL = (_ROOT / "smra" / "db" / "schema_postgres.sql").read_text(encoding="utf-8")
DEFAULT_SQLITE = _ROOT / "smra" / "data" / "smra.db"

INSERT_SQL = """
INSERT INTO stock_prices (
    symbol, company, sector, date, open, high, low, close, volume, marketcap, currency
) VALUES (
    %(symbol)s, %(company)s, %(sector)s, %(date)s,
    %(open)s, %(high)s, %(low)s, %(close)s, %(volume)s, %(marketcap)s, %(currency)s
)
"""


def _wait_for_postgres(engine, retries: int = 15, delay: float = 2.0) -> None:
    last_exc = None
    for attempt in range(1, retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            return
        except Exception as exc:
            last_exc = exc
            print(f"Waiting for Postgres ({attempt}/{retries})...")
            time.sleep(delay)
    raise RuntimeError(f"Postgres not reachable after {retries} attempts: {last_exc}")


def _bulk_insert_raw(engine, records: list[dict], batch_size: int = 500) -> None:
    """Insert rows via psycopg2 execute_batch — fully synchronous, no greenlet."""
    raw = engine.raw_connection()
    try:
        cur = raw.cursor()
        execute_batch(cur, INSERT_SQL, records, page_size=batch_size)
        raw.commit()
    finally:
        raw.close()


def migrate(sqlite_path: Path, database_url: str, truncate: bool = False) -> int:
    if not sqlite_path.exists():
        raise FileNotFoundError(f"SQLite file not found: {sqlite_path}")
    if not database_url.startswith("postgresql"):
        raise ValueError("DATABASE_URL must be a postgresql:// or postgresql+psycopg2:// URL")

    print(f"Reading SQLite: {sqlite_path}")
    df = pd.read_sql("SELECT * FROM stock_prices ORDER BY symbol, date", f"sqlite:///{sqlite_path.as_posix()}")
    if df.empty:
        raise RuntimeError("No rows found in SQLite stock_prices")
    print(f"Loaded {len(df)} rows from SQLite")

    engine = create_engine(database_url, pool_pre_ping=True)
    _wait_for_postgres(engine)

    with engine.begin() as conn:
        for stmt in SCHEMA_SQL.split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(text(stmt))
        if truncate:
            conn.execute(text("TRUNCATE TABLE stock_prices"))
        existing = conn.execute(text("SELECT COUNT(*) FROM stock_prices")).scalar() or 0
        if existing and not truncate:
            print(f"Postgres already has {existing} rows; use --truncate to replace.")
            return int(existing)

    print("Writing rows to Postgres (psycopg2 batch)...")
    records = df.to_dict(orient="records")
    for row in records:
        row["currency"] = currency_for_symbol(str(row.get("symbol", "")))
    _bulk_insert_raw(engine, records)

    with engine.connect() as conn:
        verify = conn.execute(text("SELECT COUNT(*) FROM stock_prices")).scalar()
    print(f"Migrated {len(df)} rows from SQLite -> Postgres (verified count: {verify})")
    return int(verify)


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate SMRA stock_prices SQLite -> Postgres")
    parser.add_argument("--sqlite", type=Path, default=DEFAULT_SQLITE, help="Path to smra.db")
    parser.add_argument("--database-url", default="", help="Postgres URL (or set DATABASE_URL in smra/.env)")
    parser.add_argument("--truncate", action="store_true", help="Truncate Postgres table before load")
    args = parser.parse_args()

    url = args.database_url or os.getenv("DATABASE_URL", "")
    if not url:
        print("ERROR: set DATABASE_URL in smra/.env or pass --database-url", file=sys.stderr)
        print("Example: postgresql+psycopg2://postgres:smra@127.0.0.1:5434/smra", file=sys.stderr)
        return 1
    try:
        migrate(args.sqlite, url, truncate=args.truncate)
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
