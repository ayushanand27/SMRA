import json
import re
import logging
try:
    from smra.utils.llm import call_llm
except (ModuleNotFoundError, ImportError):
    from utils.llm import call_llm

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
or {"route": ["SQL", "RAG"]} for hybrid"""

def classify_intent(query: str) -> list[str]:
    try:
        raw = call_llm(ROUTING_SYSTEM, f"Query: {query}")
        raw = raw.strip().replace("```json", "").replace("```", "").strip()
        
        # Extract JSON object
        match = re.search(r'\{.*?\}', raw, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
            routes = parsed.get("route", ["SQL"])
            valid = {"SQL", "RAG", "WEB"}
            result = [r for r in routes if r in valid]
            return result if result else ["SQL"]
    except Exception:
        logger.exception("Router failed")
    
    # Keyword fallback — never returns empty
    q = query.lower()
    if any(w in q for w in ["news", "latest", "today", "why", "recent", "analyst"]):
        return ["WEB"]
    if any(w in q for w in ["revenue", "sales", "earnings", "profit", "filing", "annual"]):
        return ["RAG"]
    return ["SQL"]