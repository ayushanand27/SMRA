import hashlib
import json
import logging
import os
import re
from datetime import datetime, timedelta

logger = logging.getLogger("smra.web")

_cache: dict = {}
CACHE_TTL_MINUTES = 60


def _cache_key(query: str) -> str:
    return hashlib.sha256(query.lower().strip().encode()).hexdigest()


def _is_cached(key: str) -> bool:
    if key not in _cache:
        return False
    return datetime.now() - _cache[key]["time"] < timedelta(minutes=CACHE_TTL_MINUTES)


def run_web_agent(user_question: str) -> dict:
    try:
        from smra.utils.llm import call_llm
        from smra.utils.schemas import error_response, success_response
    except (ModuleNotFoundError, ImportError):
        from utils.llm import call_llm
        from utils.schemas import error_response, success_response

    key = _cache_key(user_question)
    if _is_cached(key):
        logger.info("Returning cached web result")
        return _cache[key]["result"]

    try:
        from tavily import TavilyClient

        tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
        search = tavily.search(query=user_question, max_results=5)
        articles = search.get("results", [])
    except Exception as exc:
        logger.exception("Tavily search failed")
        return error_response(f"Web search failed: {exc}", error_type="io", fallback=False)

    if not articles:
        return success_response(
            answer="No web results found for that query.",
            data=[],
            meta={"sources": [], "sentiment": {"label": "Neutral", "score": 0.5}, "symbols": []},
        )

    news_text = ""
    sources = []
    for article in articles:
        news_text += f"Source: {article.get('url', '')}\n{article.get('content', '')[:300]}\n\n"
        sources.append(article.get("url", ""))

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
        raw = raw.strip().replace("```json", "").replace("```", "").strip()
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        parsed = json.loads(match.group() if match else raw)
        answer = parsed.get("answer", raw)
        sentiment = parsed.get("sentiment", {"label": "Neutral", "score": 0.5})
        symbols = parsed.get("symbols", [])
    except Exception:
        logger.exception("Web agent LLM/parse failed; using snippet fallback")
        answer = f"Here are the latest results for '{user_question}':\n\n"
        for article in articles[:3]:
            content = article.get("content", "")[:200]
            if content:
                answer += f"- {content}\n\n"
        sentiment = {"label": "Neutral", "score": 0.5}
        symbols = []

    result = success_response(
        answer=answer,
        data=articles,
        meta={"sources": sources, "sentiment": sentiment, "symbols": symbols},
    )
    result["sources"] = sources
    result["sentiment"] = sentiment
    result["symbols"] = symbols

    _cache[key] = {"result": result, "time": datetime.now()}
    return result
