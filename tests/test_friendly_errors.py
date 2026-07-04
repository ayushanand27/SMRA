"""Tests for user-facing service error messages."""
from smra.utils.friendly_errors import (
    agent_error_answer,
    friendly_db_message,
    friendly_llm_message,
    friendly_rag_message,
    friendly_web_message,
)


def test_friendly_llm_invalid_key():
    msg = friendly_llm_message(Exception("Error 401: invalid api key"))
    assert "API key" in msg


def test_friendly_llm_rate_limit():
    msg = friendly_llm_message(Exception("429 rate limit exceeded"))
    assert "rate" in msg.lower() or "quota" in msg.lower()


def test_friendly_db_connection():
    msg = friendly_db_message(Exception("connection refused"))
    assert "Postgres" in msg or "database" in msg.lower()


def test_friendly_rag_and_web_messages():
    assert "filing" in friendly_rag_message().lower()
    assert "web search" in friendly_web_message().lower()


def test_agent_error_answer_sql():
    msg = agent_error_answer("SQL", Exception("operationalerror connection refused"))
    assert "market data" in msg.lower()
