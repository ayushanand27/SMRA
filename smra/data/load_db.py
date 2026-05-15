"""Excel -> SQLite loader

Example usage:
    python load_db.py --excel ../stock_market_data.xlsx --db smra.db --table stock_prices --set-columns
"""
from pathlib import Path
import argparse
import sys
from typing import List

import pandas as pd
import sqlite3

DEFAULT_COLUMNS = [
    "symbol",
    "company",
    "sector",
    "date",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "marketcap",
]


def load_excel_to_sqlite(
    excel_path: str, sqlite_path: str, table_name: str = "stock_prices", columns: List[str] = None
) -> bool:
    """Load an Excel file into a SQLite DB, optionally renaming columns and creating an index.

    Args:
        excel_path: path to the Excel file
        sqlite_path: path to the sqlite file to create/replace
        table_name: table name to write
        columns: optional list of column names to assign to the dataframe
    """
    excel_path = Path(excel_path)
    sqlite_path = Path(sqlite_path)

    if not excel_path.exists():
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    df = pd.read_excel(excel_path)
    if columns:
        # assign provided column names (caller should ensure length matches)
        df.columns = columns

    # normalize date column if present
    if "date" in df.columns:
        try:
            df["date"] = pd.to_datetime(df["date"])
        except Exception:
            pass

    # ensure parent dir for sqlite exists
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(sqlite_path))
    try:
        df.to_sql(table_name, conn, if_exists="replace", index=False)
        # create index on symbol and date DESC
        conn.execute(f"CREATE INDEX IF NOT EXISTS idx_sym_date ON {table_name}(symbol, date DESC)")
        conn.commit()
    finally:
        conn.close()

    return True


def create_sample_excel(path: str):
    """Create a small sample Excel file useful for testing."""
    from datetime import datetime, timedelta

    path = Path(path)
    rows = []
    base = datetime.today()
    symbols = ["AAPL", "MSFT", "GOOG"]
    for s in symbols:
        for i in range(5):
            d = base - timedelta(days=i)
            rows.append(
                [
                    s,
                    f"Company {s}",
                    "Technology",
                    d.strftime("%Y-%m-%d"),
                    100 + i,
                    105 + i,
                    99 + i,
                    104 + i,
                    1000000 + i * 1000,
                    1000000000 + i * 1000,
                ]
            )

    df = pd.DataFrame(rows, columns=DEFAULT_COLUMNS)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_excel(path, index=False)


def main():
    parser = argparse.ArgumentParser(description="Load Excel into SQLite for SMRA")
    # Compute a robust default path for the Excel file relative to this script's location
    default_excel = str(Path(__file__).resolve().parent / "stock_market_data.xlsx")
    parser.add_argument("--excel", default=default_excel, help="Path to Excel file")
    parser.add_argument("--db", default="smra.db", help="SQLite DB path")
    parser.add_argument("--table", default="stock_prices", help="Table name")
    parser.add_argument("--set-columns", action="store_true", help="Set default columns on the dataframe")
    parser.add_argument(
        "--create-sample-if-missing",
        action="store_true",
        help="Create a sample Excel file if the provided path is missing",
    )
    args = parser.parse_args()

    excel_path = args.excel
    if args.create_sample_if_missing and not Path(excel_path).exists():
        print(f"Excel file {excel_path} not found. Creating sample file.")
        create_sample_excel(excel_path)

    columns = DEFAULT_COLUMNS if args.set_columns else None

    try:
        load_excel_to_sqlite(excel_path, args.db, args.table, columns=columns)
        print("Loaded Excel to SQLite successfully.")
    except Exception as e:
        print("Error:", e)
        sys.exit(1)


if __name__ == "__main__":
    main()
