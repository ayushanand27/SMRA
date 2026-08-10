import logging
import re
from typing import Optional

import pandas as pd

try:
    from smra.utils.currency import build_synthesis_notes, enrich_dataframe_currency
    from smra.utils.db import read_sql_query
    from smra.utils.llm import call_llm
    from smra.utils.schemas import error_response, success_response
except (ModuleNotFoundError, ImportError):
    from utils.currency import build_synthesis_notes, enrich_dataframe_currency
    from utils.db import read_sql_query
    from utils.schemas import error_response, success_response

    from utils.llm import call_llm

SCHEMA = """
Table: stock_prices
Columns:
  symbol     TEXT    -- US tickers e.g. AAPL, NVDA; NSE tickers use .NS suffix e.g. RELIANCE.NS
  company    TEXT    -- full company name
  sector     TEXT    -- Technology, Financials, Healthcare, Energy, Consumer Disc., Consumer Staples, etc.
  date       TEXT    -- YYYY-MM-DD string e.g. '2025-01-03'
  open       REAL    -- opening price in native currency
  high       REAL    -- intraday high (native currency)
  low        REAL    -- intraday low (native currency)
  close      REAL    -- closing price (native currency)
  volume     INTEGER -- shares traded
  marketcap  REAL    -- market cap in billions; units match the currency column (not comparable across currencies)
  currency   TEXT    -- 'USD' (US tickers) or 'INR' (*.NS NSE tickers); always SELECT with price/marketcap fields
"""

SQL_SYSTEM = f"""You are an expert SQL query writer.
Given this schema:
{SCHEMA}

Rules:
- Return ONLY a SELECT query, no explanation, no markdown, no backticks
- Always use ORDER BY date for time series
- For moving averages, fetch enough rows (e.g. LIMIT 100 for 20-day MA)
- Dates are stored as TEXT strings in 'YYYY-MM-DD' format. Always use exact string match e.g. WHERE date = '2025-01-03'
- Always include the currency column when selecting symbol, close, open, high, low, or marketcap
- Do not compare price or marketcap numerically across rows with different currency values unless the user
  explicitly asks for a cross-currency comparison; if they do, still SELECT currency and note no FX conversion exists
- For "top N by marketcap" or cross-market rankings, include currency in SELECT; prefer filtering
  WHERE currency = 'USD' or WHERE currency = 'INR' when the user asks about one market only
- This database is Postgres, which is strict about GROUP BY: every selected column must be either
  aggregated (MAX, MIN, SUM, COUNT, AVG) or listed in GROUP BY. To get "the row with the latest/highest
  value plus other columns from that same row" (e.g. latest close, top price), do NOT mix MAX()/MIN()
  with plain columns — instead use ORDER BY <column> DESC/ASC LIMIT 1 (or LIMIT N) with no GROUP BY
- Never use semicolons at the end
- Return exactly ONE SELECT statement — never two queries separated by blank lines or semicolons
- Never use DROP, DELETE, INSERT, UPDATE, ALTER, ATTACH, or PRAGMA
"""

SYNTHESIS_SYSTEM = """You are a financial analyst assistant.
Given a SQL query result, write a clear 2-4 sentence answer.
Include specific numbers. Be direct and factual.
Do not give investment advice.

Currency rules (mandatory):
- Label every price/marketcap using the currency column value for that row (USD → $ ; INR → ₹ or "INR")
- Do NOT infer currency from the symbol suffix when the currency column is present in the result
- Never label INR amounts with $ or "USD"
- marketcap values are in billions of that row's currency
- If results mix USD and INR (especially marketcap rankings), state explicitly that values are
  NOT directly comparable across currencies; no FX conversion is applied in this database
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


def _normalize_sql(raw: str) -> str:
    """Extract a single safe SELECT from LLM output (handles multi-statement replies)."""
    text = (raw or "").strip().replace("```sql", "").replace("```", "").strip()
    if not text:
        return ""

    for chunk in re.split(r";\s*|\n\s*\n+", text):
        candidate = chunk.strip().rstrip("; ")
        if _is_sql_safe(candidate):
            return candidate

    match = re.search(r"(SELECT\b.+)", text, re.I | re.DOTALL)
    if match:
        candidate = match.group(1).strip().rstrip("; ")
        first_line_break = re.split(r"\n\s*\n+", candidate, maxsplit=1)[0].strip()
        if _is_sql_safe(first_line_break):
            return first_line_break
        if _is_sql_safe(candidate):
            return candidate

    return text.rstrip("; ")


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
        "SELECT symbol, date, close FROM stock_prices "
        "WHERE symbol = :symbol ORDER BY date ASC LIMIT 1"
    )
    df = read_sql_query(fallback_sql, params={"symbol": symbol})
    return enrich_dataframe_currency(df), fallback_sql


def _build_synthesis_prompt(user_question: str, df: pd.DataFrame) -> str:
    enriched = enrich_dataframe_currency(df)
    preview = enriched.head(20).to_string(index=False)
    notes = build_synthesis_notes(user_question, enriched)
    parts = [f"User question: {user_question}", "", f"Query result (top rows):\n{preview}"]
    if notes:
        parts.extend(["", "Synthesis instructions:", notes])
    return "\n".join(parts)


def _empty_llm_output(text: str | None) -> bool:
    return not (text or "").strip()


def run_sql_agent(user_question: str) -> dict:
    """Generate SQL, validate, execute with one auto-retry on error, and synthesize answer."""
    logger = logging.getLogger("smra.sql_agent")
    sql_query = ""

    try:
        sql_query = call_llm(SQL_SYSTEM, f"Question: {user_question}")
    except Exception as exc:
        logger.exception("LLM failed to generate SQL")
        try:
            from smra.utils.friendly_errors import friendly_llm_message
        except (ModuleNotFoundError, ImportError):
            from utils.friendly_errors import friendly_llm_message
        err = error_response(friendly_llm_message(exc), error_type="llm", fallback=True)
        err["sql"] = sql_query
        return err

    sql_query = _normalize_sql(sql_query)
    logger.info("Generated SQL: %s", sql_query)

    if _empty_llm_output(sql_query):
        try:
            from smra.utils.friendly_errors import friendly_llm_message
        except (ModuleNotFoundError, ImportError):
            from utils.friendly_errors import friendly_llm_message
        return error_response(
            friendly_llm_message(RuntimeError("empty LLM response")),
            error_type="llm",
            fallback=True,
            sql=sql_query,
        )

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
            df = read_sql_query(sql_query)
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
                "Return exactly ONE corrected SELECT statement using the same rules. "
                "Do not include multiple queries, explanations, or markdown."
            )
            try:
                repaired = _normalize_sql(call_llm(SQL_SYSTEM, repair_prompt))
                if not _is_sql_safe(repaired):
                    logger.warning("Repaired SQL is unsafe, aborting retry: %s", repaired)
                    break
                sql_query = repaired
                logger.info("Repaired SQL to retry: %s", sql_query)
            except Exception:
                logger.exception("LLM failed to repair SQL")
                break

    if last_exc is not None:
        try:
            from smra.utils.friendly_errors import friendly_db_message
        except (ModuleNotFoundError, ImportError):
            from utils.friendly_errors import friendly_db_message
        err = error_response(
            friendly_db_message(last_exc),
            error_type="exec",
            fallback=True,
            sql=sql_query,
        )
        return err

    df = enrich_dataframe_currency(df)
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
        answer = call_llm(SYNTHESIS_SYSTEM, _build_synthesis_prompt(user_question, df))
    except Exception as exc:
        logger.exception("LLM failed to synthesize answer")
        try:
            from smra.utils.friendly_errors import friendly_llm_message
        except (ModuleNotFoundError, ImportError):
            from utils.friendly_errors import friendly_llm_message
        return error_response(friendly_llm_message(exc), error_type="llm", fallback=True, sql=sql_query)

    if _empty_llm_output(answer):
        try:
            from smra.utils.friendly_errors import friendly_llm_message
        except (ModuleNotFoundError, ImportError):
            from utils.friendly_errors import friendly_llm_message
        return error_response(
            friendly_llm_message(RuntimeError("empty synthesis response")),
            error_type="llm",
            fallback=True,
            sql=sql_query,
        )

    result = success_response(
        answer=answer,
        data=df,
        meta={"sql": sql_query, "confidence": confidence, "row_count": row_count},
        sql=sql_query,
    )
    return result
