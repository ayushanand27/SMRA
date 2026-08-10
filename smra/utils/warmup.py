"""One-shot warmup to avoid cold-start latency on the first user query.

Neon free tier scales to zero; sentence-transformers load is ~15–25s on CPU.
Warm both at process start so demos feel snappy.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger("smra.warmup")

_started = False
_lock = threading.Lock()


def _warm_postgres() -> None:
    try:
        from sqlalchemy import text

        try:
            from smra.utils.db import get_engine
        except (ModuleNotFoundError, ImportError):
            from utils.db import get_engine

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        logger.info("Warmup: Postgres reachable")
    except Exception as exc:
        logger.warning("Warmup: Postgres skipped (%s)", exc)


def _warm_embeddings() -> None:
    try:
        from langchain_huggingface import HuggingFaceEmbeddings

        try:
            from smra.utils.config import get_settings
        except (ModuleNotFoundError, ImportError):
            from utils.config import get_settings

        model = get_settings().embedding_model
        emb = HuggingFaceEmbeddings(model_name=model)
        emb.embed_query("warmup")
        logger.info("Warmup: embeddings ready (%s)", model)
    except Exception as exc:
        logger.warning("Warmup: embeddings skipped (%s)", exc)


def run_warmup(background: bool = True) -> None:
    """Warm Postgres + embedding model once per process."""
    global _started
    with _lock:
        if _started:
            return
        _started = True

    def _run() -> None:
        _warm_postgres()
        _warm_embeddings()

    if background:
        threading.Thread(target=_run, name="smra-warmup", daemon=True).start()
        logger.info("Warmup started in background")
    else:
        _run()
