"""Tests for history-aware query contextualization (multi-turn follow-ups)."""
from unittest.mock import patch

from smra.utils import conversation


def test_no_history_returns_query_unchanged_without_calling_llm():
    with patch.object(conversation, "call_llm") as mock_llm:
        result = conversation.contextualize_query([], "What was AAPL close?")
    assert result == "What was AAPL close?"
    mock_llm.assert_not_called()


def test_history_with_only_empty_turns_is_treated_as_no_history():
    history = [{"role": "user", "content": "   "}, {"role": "assistant", "content": ""}]
    with patch.object(conversation, "call_llm") as mock_llm:
        result = conversation.contextualize_query(history, "What was AAPL close?")
    assert result == "What was AAPL close?"
    mock_llm.assert_not_called()


def test_follow_up_gets_rewritten_using_history():
    history = [
        {"role": "user", "content": "What was AAPL revenue in 2025?"},
        {"role": "assistant", "content": "Apple's total net sales in 2025 were $416,161 million."},
    ]
    with patch.object(conversation, "call_llm", return_value="What was AAPL revenue in 2024?"):
        result = conversation.contextualize_query(history, "What about 2024?")
    assert result == "What was AAPL revenue in 2024?"


def test_llm_output_is_stripped_of_quotes_and_whitespace():
    history = [{"role": "user", "content": "Tell me about NVDA"}]
    with patch.object(conversation, "call_llm", return_value='  "What was NVDA revenue?"  '):
        result = conversation.contextualize_query(history, "what was its revenue?")
    assert result == "What was NVDA revenue?"


def test_llm_failure_falls_back_to_original_query():
    history = [{"role": "user", "content": "Tell me about NVDA"}]
    with patch.object(conversation, "call_llm", side_effect=RuntimeError("provider down")):
        result = conversation.contextualize_query(history, "what about its margins?")
    assert result == "what about its margins?"


def test_empty_llm_output_falls_back_to_original_query():
    history = [{"role": "user", "content": "Tell me about NVDA"}]
    with patch.object(conversation, "call_llm", return_value="   "):
        result = conversation.contextualize_query(history, "what about its margins?")
    assert result == "what about its margins?"


def test_history_is_trimmed_to_max_turns():
    history = [{"role": "user", "content": f"turn {i}"} for i in range(20)]
    captured = {}

    def fake_call_llm(system_prompt, user_prompt, **kwargs):
        captured["user_prompt"] = user_prompt
        return "standalone question"

    with patch.object(conversation, "call_llm", side_effect=fake_call_llm):
        conversation.contextualize_query(history, "what about that?")

    lines = captured["user_prompt"].splitlines()
    for i in range(20 - conversation.MAX_HISTORY_TURNS):
        assert f"user: turn {i}" not in lines
    assert "user: turn 19" in lines


def test_malformed_history_entries_are_ignored():
    history = [
        {"role": "system", "content": "irrelevant"},
        "not a dict",
        {"content": "missing role"},
        {"role": "user"},
    ]
    with patch.object(conversation, "call_llm") as mock_llm:
        result = conversation.contextualize_query(history, "What was AAPL close?")
    assert result == "What was AAPL close?"
    mock_llm.assert_not_called()
