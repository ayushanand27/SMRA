import logging

try:
    from smra.utils.llm import call_llm
    from smra.utils.schemas import keyword_route_fallback, validate_router_output
except (ModuleNotFoundError, ImportError):
    from utils.llm import call_llm
    from utils.schemas import keyword_route_fallback, validate_router_output

logger = logging.getLogger("smra.router")

ROUTING_SYSTEM = """You are a query router for a stock market research assistant.

Classify the query into ONE OR MORE categories. Return ONLY a JSON object.

Rules:
- SQL: stock price, closing price, opening price, volume, market cap,
       moving average, highest, lowest, best performing, worst performing,
       sector performance, price history, OHLC data
- RAG: revenue, net sales, earnings, profit, income, gross margin,
       annual report, 10-K, filing, financial statement, balance sheet,
       cash flow, guidance, R&D expenses
- WEB: news, latest, today, recent, analyst rating, price target,
       why did, what happened, current events, forecast

Return format (JSON only, no markdown):
{"route": ["SQL"]}
or {"route": ["RAG"]}
or {"route": ["WEB"]}
or {"route": ["SQL", "RAG"]} for hybrid (both market data and filings)"""


def classify_intent(query: str) -> list[str]:
    """Return route tokens such as SQL, RAG, WEB, or HYBRID."""
    try:
        raw = call_llm(ROUTING_SYSTEM, f"Query: {query}")
        routes = validate_router_output(raw)
        if routes:
            return routes
    except Exception:
        logger.exception("Router LLM call failed; using keyword fallback")

    return keyword_route_fallback(query)
