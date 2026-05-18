import os
import re
import sqlite3
import pandas as pd
import time
import logging
from typing import Optional, Tuple

try:
    from smra.utils.llm import call_llm
except Exception:
    logging.getLogger("smra.sql_agent").exception("Package import for smra.utils.llm failed; falling back to local utils.llm")
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
- Return ONLY the SQL query, no explanation, no markdown, no backticks
- Always use ORDER BY date for time series
- For moving averages, fetch enough rows (e.g. LIMIT 100 for 20-day MA)
- Dates are stored as TEXT strings in 'YYYY-MM-DD' format. Always use exact string match e.g. WHERE date = '2025-01-03'
- Never use semicolons at the end
"""

SYNTHESIS_SYSTEM = """You are a financial analyst assistant.
Given a SQL query result, write a clear 2-4 sentence answer.
Include specific numbers. Be direct and factual.
Do not give investment advice.
"""


def _is_sql_safe(sql: str) -> bool:
    """Reject destructive SQL statements."""
    banned = [r"\bDROP\b", r"\bDELETE\b", r"\bINSERT\b", r"\bUPDATE\b", r"\bALTER\b"]
    for b in banned:
        if re.search(b, sql, re.I):
            return False
    return True


def _confidence_from_rows(n: int) -> str:
    if n <= 0:
        return "low"
    if n < 50:
        return "medium"
    return "high"


def run_sql_agent(user_question: str) -> dict:
    """Generate SQL, validate, execute with one auto-retry on error, and synthesize answer.

    Returns: {answer, sql, data (DataFrame), confidence, row_count}
    """
    logger = logging.getLogger("smra.sql_agent")

    # Step 1: Generate SQL
    try:
        sql_query = call_llm(SQL_SYSTEM, f"Question: {user_question}")
    except Exception as e:
        logger.exception("LLM failed to generate SQL: %s", e)
        return {"ok": False, "error": {"msg": f"Failed to generate SQL: {e}", "type": "llm"}, "fallback": True}
    sql_query = sql_query.strip().replace("```sql", "").replace("```", "").strip()
    # strip any trailing semicolons
    sql_query = sql_query.rstrip("; ")

    # Validate SQL
    if not _is_sql_safe(sql_query):
        logger.exception("Generated SQL failed safety check: %s", sql_query)
        return {"ok": False, "error": {"msg": "The generated SQL contains disallowed statements (DROP/DELETE/INSERT/UPDATE/ALTER).", "type": "exec"}, "fallback": True}

    # Step 2: Execute with one auto-retry if execution fails
    attempt = 0
    max_attempts = 2  # original + one auto-retry
    last_exc = None
    df = pd.DataFrame()
    while attempt < max_attempts:
        try:
            conn = sqlite3.connect(DB_PATH)
            df = pd.read_sql_query(sql_query, conn)
            conn.close()
            last_exc = None
            break
        except Exception as e:
            last_exc = e
            attempt += 1
            logger.exception("SQL execution attempt %s failed: %s", attempt, e)
            if attempt >= max_attempts:
                break
            # Ask the LLM to rewrite/repair the SQL given the error
            repair_prompt = (
                f"The following SQL failed with error: {str(e)}\n\nOriginal SQL:\n{sql_query}\n\nPlease provide a corrected SQL query using the same rules. Return ONLY the SQL."
            )
            try:
                repaired = call_llm(SQL_SYSTEM, repair_prompt)
                repaired = repaired.strip().replace("```sql", "").replace("```", "").strip()
                repaired = repaired.rstrip("; ")
                # validate safety before retrying
                if not _is_sql_safe(repaired):
                    logger.warning("Repaired SQL is unsafe, aborting retry: %s", repaired)
                    break
                sql_query = repaired
            except Exception as e2:
                logger.exception("LLM failed to repair SQL: %s", e2)
                break

    if last_exc is not None:
        logger.exception("SQL execution failed after retries: %s", last_exc)
        return {"ok": False, "error": {"msg": f"I couldn't execute the query. Error: {str(last_exc)}", "type": "exec"}, "fallback": True}
    row_count = len(df)
    confidence = _confidence_from_rows(row_count)

    # Step 3: Synthesize human-readable answer (guard LLM failures)
    try:
        data_preview = df.head(20).to_string(index=False)
        answer = call_llm(
            SYNTHESIS_SYSTEM,
            f"User question: {user_question}\n\nQuery result (top rows):\n{data_preview}",
        )
    except Exception as e:
        logger.exception("LLM failed to synthesize answer: %s", e)
        # Synthesis failed, but query executed successfully — return a sensible answer and keep ok=True
        answer = f"Query executed successfully. Returned {row_count} rows."

    return {"ok": True, "answer": answer, "data": df, "meta": {"sql": sql_query, "confidence": confidence, "row_count": row_count}}
