import logging
import os
import re
import sqlite3
from typing import Optional

import pandas as pd

try:
    from smra.utils.llm import call_llm
    from smra.utils.schemas import error_response, success_response
except (ModuleNotFoundError, ImportError):
    from utils.schemas import error_response, success_response

    from utils.llm import call_llm

DB_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "smra.db"))

SCHEMA = """
SQLite table: stock_prices
Columns:
  symbol     TEXT    -- ticker e.g. AAPL, NVDA, TSLA
  company    TEXT    -- full company name
  sector     TEXT    -- Technology, Financials, Healthcare, Energy, Consumer Disc., Consumer Staples
  date       TEXT    -- YYYY-MM-DD string e.g. '2025-01-03'
  open       REAL    -- opening price
  high       REAL    -- intraday high
  low        REAL    -- intraday low
  close      REAL    -- closing price
  volume     INTEGER -- shares traded
  marketcap  REAL    -- market cap in billions USD
"""

SQL_SYSTEM = f"""You are an expert SQLite query writer.
Given this schema:
{SCHEMA}

Rules:
- Return ONLY a SELECT query, no explanation, no markdown, no backticks
- Always use ORDER BY date for time series
- For moving averages, fetch enough rows (e.g. LIMIT 100 for 20-day MA)
- Dates are stored as TEXT strings in 'YYYY-MM-DD' format. Always use exact string match e.g. WHERE date = '2025-01-03'
- Never use semicolons at the end
- Never use DROP, DELETE, INSERT, UPDATE, ALTER, ATTACH, or PRAGMA
"""

SYNTHESIS_SYSTEM = """You are a financial analyst assistant.
Given a SQL query result, write a clear 2-4 sentence answer.
Include specific numbers. Be direct and factual.
Do not give investment advice.
"""

_BANNED_SQL = re.compile(
    r"\b(DROP|DELETE|INSERT|UPDATE|ALTER|ATTACH|PRAGMA|CREATE|REPLACE|TRUNCATE|GRANT|REVOKE)\b",
    re.I,
)


def _is_sql_safe(sql: str) -> bool:
    """Reject destructive or non-read SQL statements."""
    if not sql or not sql.strip():
        return False
    if _BANNED_SQL.search(sql):
        return False
    return bool(re.match(r"^\s*SELECT\b", sql, re.I | re.DOTALL))


def _confidence_from_rows(n: int) -> str:
    if n <= 0:
        return "low"
    if n < 50:
        return "medium"
    return "high"


def _extract_symbol_from_sql(sql_query: str) -> Optional[str]:
    match = re.search(r"symbol\s*=\s*['\"]([A-Za-z0-9.\-]+)['\"]", sql_query, re.I)
    return match.group(1).upper() if match else None


def _run_fallback_query(symbol: str) -> tuple[pd.DataFrame, str]:
    """Parameterized fallback when the primary query returns no rows."""
    fallback_sql = (
        "SELECT symbol, date, close FROM stock_prices WHERE symbol = ? ORDER BY date ASC LIMIT 1"
    )
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(fallback_sql, conn, params=(symbol,))
    finally:
        conn.close()
    return df, fallback_sql


def run_sql_agent(user_question: str) -> dict:
    """Generate SQL, validate, execute with one auto-retry on error, and synthesize answer."""
    logger = logging.getLogger("smra.sql_agent")
    sql_query = ""

    try:
        sql_query = call_llm(SQL_SYSTEM, f"Question: {user_question}")
    except Exception as exc:
        logger.exception("LLM failed to generate SQL")
        err = error_response(f"Failed to generate SQL: {exc}", error_type="llm", fallback=True)
        err["sql"] = sql_query
        return err

    sql_query = sql_query.strip().replace("```sql", "").replace("```", "").strip().rstrip("; ")
    logger.info("Generated SQL: %s", sql_query)

    if not _is_sql_safe(sql_query):
        logger.warning("Generated SQL failed safety check: %s", sql_query)
        err = error_response(
            "The generated SQL contains disallowed statements or is not a SELECT query.",
            error_type="exec",
            fallback=True,
            sql=sql_query,
        )
        return err

    attempt = 0
    max_attempts = 2
    last_exc = None
    df = pd.DataFrame()

    while attempt < max_attempts:
        try:
            conn = sqlite3.connect(DB_PATH)
            df = pd.read_sql_query(sql_query, conn)
            conn.close()
            last_exc = None
            break
        except Exception as exc:
            last_exc = exc
            attempt += 1
            logger.exception("SQL execution attempt %s failed", attempt)
            if attempt >= max_attempts:
                break
            repair_prompt = (
                f"The following SQL failed with error: {exc}\n\n"
                f"Original SQL:\n{sql_query}\n\n"
                "Please provide a corrected SELECT query using the same rules. Return ONLY the SQL."
            )
            try:
                repaired = call_llm(SQL_SYSTEM, repair_prompt)
                repaired = repaired.strip().replace("```sql", "").replace("```", "").strip().rstrip("; ")
                if not _is_sql_safe(repaired):
                    logger.warning("Repaired SQL is unsafe, aborting retry: %s", repaired)
                    break
                sql_query = repaired
                logger.info("Repaired SQL to retry: %s", sql_query)
            except Exception:
                logger.exception("LLM failed to repair SQL")
                break

    if last_exc is not None:
        err = error_response(
            f"I couldn't execute the query. Error: {last_exc}",
            error_type="exec",
            fallback=True,
            sql=sql_query,
        )
        return err

    row_count = len(df)
    confidence = _confidence_from_rows(row_count)

    if row_count == 0:
        symbol = _extract_symbol_from_sql(sql_query) or "AAPL"
        try:
            df_fallback, fallback_sql = _run_fallback_query(symbol)
            if not df_fallback.empty:
                logger.info("Original query returned empty; using fallback for symbol=%s", symbol)
                df = df_fallback
                sql_query = fallback_sql
                row_count = len(df)
                confidence = _confidence_from_rows(row_count)
        except Exception:
            logger.exception("Fallback query failed for symbol=%s", symbol)

    try:
        data_preview = df.head(20).to_string(index=False)
        answer = call_llm(
            SYNTHESIS_SYSTEM,
            f"User question: {user_question}\n\nQuery result (top rows):\n{data_preview}",
        )
    except Exception:
        logger.exception("LLM failed to synthesize answer")
        answer = f"Query executed successfully. Returned {row_count} rows."

    result = success_response(
        answer=answer,
        data=df,
        meta={"sql": sql_query, "confidence": confidence, "row_count": row_count},
        sql=sql_query,
    )
    return result
