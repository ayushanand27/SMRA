import os
import json
from utils.llm import call_llm

ROUTING_SYSTEM = """You are a query router for a stock market research assistant.
Classify the user query into one or more categories:
- SQL: historical prices, moving averages, sector performance, volume, returns, rankings
- RAG: annual reports, 10-K filings, revenue, earnings, guidance, risk factors, fundamentals
- WEB: recent news, latest, today, analyst ratings, earnings announcements, why did X move

Reply with ONLY valid JSON. Example: {"route": ["SQL"]} or {"route": ["WEB", "SQL"]}
No explanation, no markdown, just the JSON object."""


def classify_intent(query: str) -> list[str]:
    q = (query or "").strip().lower()
    valid = {"SQL", "RAG", "WEB"}

    def env_bool(name: str, default: bool = False) -> bool:
        v = os.getenv(name)
        if v is None:
            return default
        return v.strip().lower() in {"1", "true", "yes", "y", "on"}

    # --- Fast heuristic router (prevents blocking on LLM calls) ---
    sql_hints = [
        "price",
        "close",
        "open",
        "high",
        "low",
        "volume",
        "moving average",
        "ma ",
        "sma",
        "ema",
        "return",
        "returns",
        "volatility",
        "rsi",
        "macd",
    ]
    rag_hints = [
        "10-k",
        "10k",
        "annual report",
        "form 10",
        "filing",
        "net sales",
        "revenue",
        "gross margin",
        "operating income",
        "guidance",
        "eps",
        "cash flow",
        "balance sheet",
        "segment",
        "risk factor",
        "risk factors",
    ]
    web_hints = [
        "news",
        "latest",
        "today",
        "recent",
        "headline",
        "why did",
        "why is",
        "what happened",
        "rumor",
        "rating",
        "downgrade",
        "upgrade",
        "earnings call",
    ]

    routes = []
    if any(h in q for h in web_hints):
        routes.append("WEB")
    if any(h in q for h in rag_hints):
        routes.append("RAG")
    if any(h in q for h in sql_hints):
        routes.append("SQL")

    # Default router mode:
    # - heuristic: never call LLM
    # - hybrid: use heuristics, else LLM
    # - llm: always call LLM
    mode = os.getenv("ROUTER_MODE", "hybrid").strip().lower()

    if mode in {"heuristic", "fast"}:
        return routes or ["SQL"]

    if mode in {"hybrid", "auto"} and routes:
        # Heuristics already decided.
        return [r for r in routes if r in valid] or ["SQL"]

    # Allow disabling LLM routing entirely even in hybrid mode.
    if env_bool("ROUTER_DISABLE_LLM", False):
        return routes or ["SQL"]

    # --- LLM router fallback ---
    try:
        result = call_llm(ROUTING_SYSTEM, query)
        # Clean markdown if model adds it
        result = result.strip().replace("```json", "").replace("```", "").strip()
        parsed = json.loads(result)
        llm_routes = parsed.get("route", ["SQL"])
        llm_routes = [r for r in llm_routes if r in valid]
        return llm_routes or routes or ["SQL"]
    except Exception:
        return routes or ["SQL"]  # safe fallback
