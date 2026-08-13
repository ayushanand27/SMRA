"""MCP server exposing SMRA as a tool for other AI agents (Claude Desktop, Claude Code, etc.)

The 2026 trend among AI-finance platforms (OpenBB in particular) is exposing themselves
via the Model Context Protocol so any MCP-capable agent can call them as a tool instead of
being locked to one chat UI. This wraps the same answer_query() pipeline used by the
FastAPI /query endpoint and the Streamlit UI -- one pipeline, three front doors.

Run directly:
    python -m smra.mcp_server

Runs over stdio (the standard local-MCP-server transport): no network port, no API-key
auth -- the trust boundary is "who can spawn this process on this machine," the same model
Claude Desktop/Code use for every local MCP server. Add GROQ_API_KEY etc. to smra/.env as
usual; DATABASE_URL unset falls back to the bundled SQLite dataset like every other entry
point.
"""
import logging

from mcp.server.fastmcp import FastMCP

try:
    from smra.orchestrator import answer_query
    from smra.utils.config import get_settings
    from smra.utils.observability import configure_logging
except (ModuleNotFoundError, ImportError):
    from orchestrator import answer_query
    from utils.config import get_settings
    from utils.observability import configure_logging

settings = get_settings()
configure_logging(level=settings.log_level, json_logs=settings.json_logs)
logger = logging.getLogger("smra.mcp_server")

mcp = FastMCP(
    "smra",
    instructions=(
        "Stock Market Research Assistant: ask natural-language questions about US/India stock "
        "prices and history (50 tickers), 8 real company 10-K filings (Apple, NVIDIA, Amazon, "
        "Microsoft, Tesla, JPMorgan Chase, TCS, Reliance), or live market news. Not financial advice."
    ),
)


@mcp.tool()
def ask_smra(query: str) -> dict:
    """Ask the Stock Market Research Assistant a question.

    Automatically routes to structured market data (SQL over 50 US/India tickers), company
    filing excerpts (RAG over 8 real 10-Ks, with citations), live web news, or a combination.
    Moving averages, % return, CAGR, volatility, and 52-week high/low are computed
    deterministically in Python, not estimated by an LLM. Not financial advice.

    Args:
        query: A natural-language question, e.g. "What was NVDA's 20-day moving average?" or
            "What was Apple's total net sales in the 10-K?"
    """
    result = answer_query(query)
    return {
        "answer": result["answer"],
        "routes": result["routes"],
        "sql": result.get("sql", ""),
        "sources": result.get("sources", []),
        "ok": result.get("ok", True),
    }


if __name__ == "__main__":
    mcp.run()
