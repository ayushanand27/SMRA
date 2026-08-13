"""Tests for the MCP server's tool-response shaping.

The actual MCP protocol (tool discovery + call over stdio) was verified manually with the
real client SDK against a live subprocess -- that's not something worth re-running on every
CI build. These tests cover what unit tests are good at: the response shape is stable and
answer_query() is actually being called with the right arguments.
"""
from unittest.mock import patch

from smra import mcp_server


def test_ask_smra_is_registered_as_an_mcp_tool():
    tools = mcp_server.mcp._tool_manager.list_tools()
    assert [t.name for t in tools] == ["ask_smra"]


def test_ask_smra_calls_answer_query_and_shapes_response():
    fake_result = {
        "query_id": "abc123",
        "routes": ["SQL"],
        "answer": "AAPL closed at $200.",
        "sql": "SELECT close FROM stock_prices",
        "sources": [],
        "grounded": None,
        "ok": True,
        "resolved_query": None,
    }
    with patch.object(mcp_server, "answer_query", return_value=fake_result) as mock_answer:
        out = mcp_server.ask_smra("What was AAPL's close?")

    mock_answer.assert_called_once_with("What was AAPL's close?")
    assert out == {
        "answer": "AAPL closed at $200.",
        "routes": ["SQL"],
        "sql": "SELECT close FROM stock_prices",
        "sources": [],
        "ok": True,
    }


def test_ask_smra_defaults_ok_true_when_missing():
    fake_result = {"answer": "some answer", "routes": ["WEB"]}
    with patch.object(mcp_server, "answer_query", return_value=fake_result):
        out = mcp_server.ask_smra("recent news on TSLA")
    assert out["ok"] is True
    assert out["sql"] == ""
    assert out["sources"] == []
