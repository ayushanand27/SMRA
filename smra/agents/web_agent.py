import os
import re
import json
import time
import logging
import hashlib
from datetime import datetime, timedelta

logger = logging.getLogger("smra.web")

_cache: dict = {}
CACHE_TTL_MINUTES = 60

def _cache_key(query: str) -> str:
    return hashlib.md5(query.lower().strip().encode()).hexdigest()

def _is_cached(key: str) -> bool:
    if key not in _cache:
        return False
    return datetime.now() - _cache[key]["time"] < timedelta(minutes=CACHE_TTL_MINUTES)

def run_web_agent(user_question: str) -> dict:
    try:
        from smra.utils.llm import call_llm
    except (ModuleNotFoundError, ImportError):
        from utils.llm import call_llm

    key = _cache_key(user_question)
    if _is_cached(key):
        logger.info("Returning cached web result")
        return _cache[key]["result"]

    try:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
        search = tavily.search(query=user_question, max_results=5)
        articles = search.get("results", [])
    except Exception as e:
        logger.exception("Tavily search failed")
        return {"answer": f"Web search failed: {str(e)}", "sources": []}

    if not articles:
        return {"answer": "No web results found for that query.", "sources": []}

    # Build context
    news_text = ""
    sources = []
    for r in articles:
        news_text += f"Source: {r.get('url','')}\n{r.get('content','')[:300]}\n\n"
        sources.append(r.get("url", ""))

    # Single LLM call for everything
    system = """You are a financial news analyst. Given news results, 
return ONLY a valid JSON object with exactly these three fields:
{
  "answer": "3-4 sentence summary of the news",
  "sentiment": {"label": "Positive", "score": 0.75},
  "symbols": ["AAPL", "NVDA"]
}
No markdown fences, no explanation. Just the JSON object."""

    user = f"News:\n{news_text}\n\nQuestion: {user_question}"

    try:
        raw = call_llm(system, user)
        # Strip markdown fences if present
        raw = raw.strip().replace("```json", "").replace("```", "").strip()
        # Extract first { ... } block
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            parsed = json.loads(match.group())
        else:
            parsed = json.loads(raw)

        answer = parsed.get("answer", raw)
        sentiment = parsed.get("sentiment", {"label": "Neutral", "score": 0.5})
        symbols = parsed.get("symbols", [])

    except Exception as e:
        logger.exception("Web agent LLM/parse failed")
        # Build answer directly from article snippets without LLM
        answer = f"Here are the latest results for '{user_question}':\n\n"
        for r in articles[:3]:
            content = r.get('content', '')[:200]
            url = r.get('url', '')
            if content:
                answer += f"• {content}\n\n"
        sentiment = {"label": "Neutral", "score": 0.5}
        symbols = []

    result = {
        "answer": answer,
        "sources": sources,
        "sentiment": sentiment,
        "symbols": symbols,
        "ok": True
    }

    _cache[key] = {"result": result, "time": datetime.now()}
    return result
