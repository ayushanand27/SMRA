"""Tests for /query error propagation and non-empty answers."""
from unittest.mock import patch

from smra.utils.schemas import error_response, success_response


def test_agent_answer_uses_error_payload_message():
    from smra.api import _agent_answer

    msg = "The LLM service rejected the API key."
    result = error_response(msg, error_type="llm")
    assert _agent_answer(result, "SQL") == msg


def test_agent_answer_never_returns_empty_on_success_without_text():
    from smra.api import _agent_answer

    result = success_response(answer="", sql="SELECT 1")
    out = _agent_answer(result, "SQL")
    assert out.strip()
    assert "market data" in out.lower() or "language model" in out.lower() or "try again" in out.lower()


def test_sql_agent_empty_llm_sql_returns_friendly_error():
    from smra.agents import sql_agent

    with patch.object(sql_agent, "call_llm", return_value="   "):
        result = sql_agent.run_sql_agent("What was AAPL close?")
    assert result["ok"] is False
    assert result["answer"].strip()
    assert "language model" in result["answer"].lower() or "unavailable" in result["answer"].lower()
