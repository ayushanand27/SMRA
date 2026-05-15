import sqlite3
from pathlib import Path
import pandas as pd

DB = Path(__file__).resolve().parent.parent / "data" / "smra.db"
print("DB path:", DB)
if not DB.exists():
    print("Database not found. Run data/load_db.py first.")
    raise SystemExit(1)

conn = sqlite3.connect(str(DB))
try:
    df = pd.read_sql_query("SELECT DISTINCT symbol FROM stock_prices ORDER BY symbol", conn)
    print("Symbols:", df['symbol'].tolist())
    range_df = pd.read_sql_query(
        "SELECT symbol, MIN(date) as min_date, MAX(date) as max_date, COUNT(*) as rows FROM stock_prices GROUP BY symbol ORDER BY symbol",
        conn,
    )
    print('\nPer-symbol date ranges:')
    print(range_df.to_string(index=False))
finally:
    conn.close()
