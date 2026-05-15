import os
from utils.llm import call_llm

WEB_SYSTEM = """You are a financial news analyst.
Summarize the news results to answer the question.
Add a sentiment label at the end: [Sentiment: Positive / Neutral / Negative]
Keep your answer under 150 words. Mention source URLs briefly."""


def run_web_agent(user_question: str) -> dict:
    try:
        from tavily import TavilyClient
        tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
        results = tavily.search(query=user_question, max_results=5)
        news_text = ""
        for r in results.get("results", []):
            news_text += f"Source: {r['url']}\n{r['content'][:300]}\n\n"
        sources = [r["url"] for r in results.get("results", [])]
    except Exception as e:
        return {"answer": f"Web search failed: {str(e)}", "sources": []}

    answer = call_llm(
        WEB_SYSTEM,
        f"News results:\n{news_text}\n\nQuestion: {user_question}",
    )
    return {"answer": answer, "sources": sources}
