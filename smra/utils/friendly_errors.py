"""User-facing error messages for external service failures."""
from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

logger = logging.getLogger("smra.errors")

T = TypeVar("T")


def friendly_llm_message(exc: BaseException) -> str:
    text = str(exc).lower()
    if "401" in text or "invalid api key" in text or "invalid_api_key" in text:
        return (
            "The LLM service rejected the API key. Check GROQ_API_KEY (or your configured "
            "LLM_PROVIDER key) in smra/.env and try again."
        )
    if "429" in text or "rate limit" in text or "quota" in text:
        return (
            "The LLM service is rate-limited or out of quota. Please wait a moment and try again."
        )
    if "timeout" in text or "timed out" in text:
        return "The LLM service timed out. Please try again in a few seconds."
    return "The language model service is temporarily unavailable. Please try again shortly."


def friendly_db_message(exc: BaseException) -> str:
    text = str(exc).lower()
    if "connection refused" in text or "could not connect" in text or "operationalerror" in text:
        return (
            "Market data database is unreachable. Check that Postgres is running and "
            "DATABASE_URL in smra/.env is correct."
        )
    if "authentication failed" in text or "password authentication" in text:
        return "Database authentication failed. Verify DATABASE_URL credentials."
    return "Market data is temporarily unavailable due to a database error."


def friendly_rag_message(exc: BaseException | None = None) -> str:
    if exc is not None:
        logger.debug("RAG degradation reason: %s", exc)
    return (
        "Filing search is temporarily unavailable. I can still answer from market data "
        "or web search if those routes are selected."
    )


def friendly_web_message(exc: BaseException | None = None) -> str:
    if exc is not None:
        logger.debug("Web degradation reason: %s", exc)
    return (
        "Web search is temporarily unavailable. Answering from database and filing data only."
    )


def agent_error_answer(agent: str, exc: BaseException) -> str:
    agent = agent.upper()
    if agent == "SQL":
        return f"I couldn't query market data right now. {friendly_db_message(exc)}"
    if agent == "RAG":
        return friendly_rag_message(exc)
    if agent == "WEB":
        return friendly_web_message(exc)
    if agent == "LLM":
        return friendly_llm_message(exc)
    return "Something went wrong while processing your request. Please try again."


def safe_agent_call(agent: str, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T | dict:
    """Run an agent callable; return a dict error payload instead of raising."""
    try:
        from smra.utils.schemas import error_response
    except (ModuleNotFoundError, ImportError):
        from utils.schemas import error_response

    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        logger.exception("%s agent failed", agent)
        msg = agent_error_answer(agent, exc)
        return error_response(msg, error_type="service", fallback=(agent in {"RAG", "WEB"}))
