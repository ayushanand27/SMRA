"""Tracked, idempotent Postgres migration runner.

Applies smra/db/schema_postgres.sql (baseline) and smra/db/migrations/*.sql
(incremental) in order, recording each in a `schema_migrations` table so a
file never runs twice — across local, CI, and every deployed environment.

Usage: python -m smra.db.migrate
"""
import logging
import re
from pathlib import Path

from sqlalchemy import text

try:
    from smra.utils.config import get_settings
    from smra.utils.db import get_engine
except (ModuleNotFoundError, ImportError):
    from utils.config import get_settings
    from utils.db import get_engine

logger = logging.getLogger("smra.db.migrate")

_DB_DIR = Path(__file__).resolve().parent
_BASELINE_SQL = _DB_DIR / "schema_postgres.sql"
_MIGRATIONS_DIR = _DB_DIR / "migrations"
_VERSION_RE = re.compile(r"^(\d+)_")


def _ensure_tracking_table(conn) -> None:
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now()
            )
            """
        )
    )


def _applied_versions(conn) -> set[str]:
    rows = conn.execute(text("SELECT version FROM schema_migrations")).fetchall()
    return {row[0] for row in rows}


def _pending_files() -> list[tuple[str, Path]]:
    files: list[tuple[str, Path]] = []
    if _BASELINE_SQL.exists():
        files.append(("000_baseline", _BASELINE_SQL))
    for path in sorted(_MIGRATIONS_DIR.glob("*.sql")):
        match = _VERSION_RE.match(path.name)
        version = match.group(1) if match else path.stem
        files.append((version, path))
    return files


def run_migrations() -> list[str]:
    """Apply every not-yet-applied migration in order. Returns the versions applied."""
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError(
            "DATABASE_URL is not set; migrations only apply to Postgres, not the SQLite fallback."
        )

    engine = get_engine()
    with engine.begin() as conn:
        _ensure_tracking_table(conn)
        done = _applied_versions(conn)

    applied: list[str] = []
    for version, path in _pending_files():
        if version in done:
            continue
        sql = path.read_text(encoding="utf-8")
        logger.info("Applying migration %s (%s)", version, path.name)
        with engine.begin() as conn:
            conn.execute(text(sql))
            conn.execute(text("INSERT INTO schema_migrations (version) VALUES (:v)"), {"v": version})
        applied.append(version)

    if applied:
        logger.info("Applied %d migration(s): %s", len(applied), ", ".join(applied))
    else:
        logger.info("No pending migrations.")
    return applied


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    run_migrations()
