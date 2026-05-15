import os
import re
import sqlite3
import pandas as pd
from typing import Optional, Tuple

from utils.llm import call_llm

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "smra.db"))

SCHEMA = """
SQLite table: stock_prices
Columns:
  symbol     TEXT    -- ticker e.g. AAPL, NVDA, TSLA
  company    TEXT    -- full company name
  sector     TEXT    -- Technology, Financials, Healthcare, Energy, Consumer Disc., Consumer Staples
    date       TEXT    -- YYYY-MM-DD string e.g. '2025-01-03'. Use exact string match: WHERE date = '2025-01-03'
  open       REAL    -- opening price
  high       REAL    -- intraday high
  low        REAL    -- intraday low
  close      REAL    -- closing price
  volume     INTEGER -- shares traded
  marketcap  REAL    -- market cap in billions USD

Available symbols: AAPL, MSFT, GOOGL, NVDA, META, JPM, BAC, GS, V, MA,
  JNJ, UNH, PFE, ABBV, MRK, XOM, CVX, COP, SLB, EOG,
  AMZN, TSLA, HD, MCD, NKE, PG, KO, WMT, COST, CL
"""



SQL_SYSTEM = f"""You are an expert SQLite query writer.
Given this schema:
{SCHEMA}

Rules:
- Return ONLY the SQL query, no explanation, no markdown, no backticks
- Always use ORDER BY date for time series
- For moving averages, fetch enough rows (e.g. LIMIT 100 for 20-day MA)
- Dates are stored as TEXT strings in 'YYYY-MM-DD' format. Always use exact string match e.g. WHERE date = '2025-01-03'
- 2025-01-03 IS a valid trading day in the database
- Use strftime for date filtering if needed
- Never use semicolons at the end"""

SYNTHESIS_SYSTEM = """You are a financial analyst assistant.
Given a SQL query result, write a clear 2-4 sentence answer.
Include specific numbers. Be direct and factual.
Do not give investment advice."""


def run_sql_agent(user_question: str) -> dict:
    # Step 1: Generate SQL
    sql_query = call_llm(SQL_SYSTEM, f"Question: {user_question}")
    sql_query = sql_query.strip().replace("```sql", "").replace("```", "").strip()

    # Step 2: Execute
    try:
        conn = sqlite3.connect(DB_PATH)
        df = pd.read_sql_query(sql_query, conn)
        conn.close()
    except Exception as e:
        return {
            "answer": f"I couldn't execute the query. Error: {str(e)}",
            "data": pd.DataFrame(),
            "sql": sql_query,
        }

    if df.empty:
        # Try to extract a ticker symbol and/or date from the SQL or the user question
        def extract_symbol_and_date(sql: str, question: str) -> Tuple[Optional[str], Optional[str]]:
            # Known symbols from the schema
            known = [
                "AAPL","MSFT","GOOGL","NVDA","META","JPM","BAC","GS","V","MA",
                "JNJ","UNH","PFE","ABBV","MRK","XOM","CVX","COP","SLB","EOG",
                "AMZN","TSLA","HD","MCD","NKE","PG","KO","WMT","COST","CL",
            ]

            # Attempt to find symbol in SQL like: symbol = 'AAPL'
            m = re.search(r"symbol\s*=\s*['\"]([A-Z0-9\.]+)['\"]", sql, re.I)
            if m:
                date_match = re.search(r"(\d{4}-\d{2}-\d{2})", sql) or re.search(r"(\d{4}-\d{2}-\d{2})", question)
                return m.group(1).upper(), date_match.group(1) if date_match else None

            # Otherwise look in the user question for a known ticker
            uq = question.upper()
            for s in known:
                if re.search(rf"\b{s}\b", uq):
                    date_match = re.search(r"(\d{4}-\d{2}-\d{2})", question)
                    return s, date_match.group(1) if date_match else None

            return None, None

        symbol, date = extract_symbol_and_date(sql_query, user_question)

        # If we found a symbol, try a nearest-date fallback
        if symbol:
            try:
                conn = sqlite3.connect(DB_PATH)
                if date:
                    # nearest previous or equal date
                    fb_q = f"SELECT * FROM stock_prices WHERE symbol = '{symbol}' AND date <= '{date}' ORDER BY date DESC LIMIT 1"
                    fb_df = pd.read_sql_query(fb_q, conn)
                else:
                    fb_q = f"SELECT * FROM stock_prices WHERE symbol = '{symbol}' ORDER BY date DESC LIMIT 1"
                    fb_df = pd.read_sql_query(fb_q, conn)
                conn.close()
            except Exception:
                fb_df = pd.DataFrame()

            if not fb_df.empty:
                # Compose a helpful answer pointing to the nearest available date
                try:
                    nearest_date = str(fb_df.iloc[0]["date"])
                    close_val = fb_df.iloc[0].get("close")
                    answer_text = (
                        f"I couldn't find data for {symbol} on {date}. "
                        if date
                        else "No exact match found for that query. "
                    )
                    answer_text += f"The nearest available date is {nearest_date} with closing price {close_val}."
                except Exception:
                    answer_text = "No data found for that query in the database."

                return {"answer": answer_text, "data": fb_df, "sql": sql_query}
            else:
                # If we searched for a specific date but found nothing, fall back to most recent
                if date:
                    try:
                        conn = sqlite3.connect(DB_PATH)
                        fb_q2 = f"SELECT * FROM stock_prices WHERE symbol = '{symbol}' ORDER BY date DESC LIMIT 1"
                        fb_df2 = pd.read_sql_query(fb_q2, conn)
                        conn.close()
                    except Exception:
                        fb_df2 = pd.DataFrame()

                    if not fb_df2.empty:
                        try:
                            nearest_date = str(fb_df2.iloc[0]["date"])
                            close_val = fb_df2.iloc[0].get("close")
                            answer_text = (
                                f"I couldn't find data for {symbol} on {date}. "
                                f"The most recent available date is {nearest_date} with closing price {close_val}."
                            )
                        except Exception:
                            answer_text = "No data found for that query in the database."
                        return {"answer": answer_text, "data": fb_df2, "sql": sql_query}

        # No useful fallback found
        return {"answer": "No data found for that query in the database.", "data": df, "sql": sql_query}

    # Step 3: Synthesize
    data_preview = df.head(20).to_string(index=False)
    answer = call_llm(
        SYNTHESIS_SYSTEM,
        f"User question: {user_question}\n\nQuery result:\n{data_preview}",
    )

    return {"answer": answer, "data": df, "sql": sql_query}
