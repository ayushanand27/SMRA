"""Audit trail for replayability (regulator-defensible logging).

Persists one row per user request: the query, routing decision, generated SQL,
retrieved sources, final answer, provider/model, and latency. This makes any
past answer reproducible/inspectable, a baseline requirement for financial AI.
"""
import json
import logging
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("smra.audit")

_AUDIT_DB = Path(__file__).resolve().parents[1] / "data" / "audit.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    query_id TEXT,
    ts REAL,
    query TEXT,
    routes TEXT,
    sql TEXT,
    sources TEXT,
    answer TEXT,
    provider TEXT,
    model TEXT,
    latency_ms REAL,
    ok INTEGER
);
"""


def _connect() -> sqlite3.Connection:
    _AUDIT_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_AUDIT_DB))
    conn.execute(_SCHEMA)
    return conn


def record(
    query_id: str,
    query: str,
    routes: Any,
    answer: str,
    sql: str = "",
    sources: Optional[list] = None,
    provider: str = "",
    model: str = "",
    latency_ms: float = 0.0,
    ok: bool = True,
) -> None:
    """Best-effort audit write; never raises into the request path."""
    try:
        conn = _connect()
        try:
            conn.execute(
                """
                INSERT INTO audit_log
                    (query_id, ts, query, routes, sql, sources, answer, provider, model, latency_ms, ok)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    query_id,
                    time.time(),
                    query,
                    json.dumps(routes, default=str),
                    sql,
                    json.dumps(sources or [], default=str),
                    answer,
                    provider,
                    model,
                    latency_ms,
                    1 if ok else 0,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        logger.exception("Failed to write audit record")


def recent(limit: int = 20) -> list[dict]:
    """Return recent audit rows (for inspection / replay)."""
    try:
        conn = _connect()
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cur.fetchall()]
        finally:
            conn.close()
    except Exception:
        logger.exception("Failed to read audit records")
        return []
