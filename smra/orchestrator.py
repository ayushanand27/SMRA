"""Multi-agent orchestration helpers (e.g. HYBRID synthesis)."""
import logging

try:
    from smra.utils.llm import call_llm
except (ModuleNotFoundError, ImportError):
    from utils.llm import call_llm

logger = logging.getLogger("smra.orchestrator")

HYBRID_SYNTHESIS_SYSTEM = """You are a financial research assistant.
Combine structured market data (SQL) and filing excerpts (RAG) into one concise answer.
- Include specific numbers from both sources when available.
- Cite filing sources by filename/page when mentioned in the RAG section.
- Do not give investment advice.
- If one source is missing or weak, say so briefly and answer from the other.
"""


def synthesize_hybrid_answer(user_question: str, sql_result: dict, rag_result: dict) -> str:
    """Merge SQL and RAG agent outputs into a single response."""
    sql_answer = (sql_result or {}).get("answer", "").strip()
    rag_answer = (rag_result or {}).get("answer", "").strip()
    sql_ok = (sql_result or {}).get("ok", False)
    rag_ok = (rag_result or {}).get("ok", False)

    if sql_ok and rag_ok and sql_answer and rag_answer:
        prompt = (
            f"User question: {user_question}\n\n"
            f"SQL market data answer:\n{sql_answer}\n\n"
            f"Filing/RAG answer:\n{rag_answer}\n\n"
            "Write a unified 4-6 sentence answer."
        )
        try:
            return call_llm(HYBRID_SYNTHESIS_SYSTEM, prompt).strip()
        except Exception as exc:
            logger.exception("Hybrid synthesis LLM call failed")
            try:
                from smra.utils.friendly_errors import friendly_llm_message
            except (ModuleNotFoundError, ImportError):
                from utils.friendly_errors import friendly_llm_message
            return friendly_llm_message(exc)

    parts = []
    if sql_answer:
        parts.append(f"**Market data:** {sql_answer}")
    if rag_answer:
        parts.append(f"**Filings:** {rag_answer}")
    if parts:
        return "\n\n".join(parts)

    return "I could not retrieve enough data from market records or filings to answer that question."
