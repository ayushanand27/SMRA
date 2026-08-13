"""Multi-agent orchestration: the single "how SMRA answers a question" pipeline.

answer_query() is the one place that implements guardrails -> contextualize -> cache ->
route -> agents -> synthesize -> cache-write -> audit. Both the FastAPI /query endpoint
and the MCP server (smra/mcp_server.py) call it, so neither can accidentally skip a
safety or auditing step by reimplementing the pipeline slightly differently — before this
existed, that logic was duplicated (and drifting) between api.py and app.py.
"""
import logging
import time
from typing import Any, Optional

try:
    from smra.agents.rag_agent import run_rag_agent
    from smra.agents.sql_agent import run_sql_agent
    from smra.agents.web_agent import run_web_agent
    from smra.cache.semantic_cache import get_cached_answer, set_cached_answer
    from smra.router import classify_intent
    from smra.utils import audit
    from smra.utils.config import get_settings
    from smra.utils.conversation import contextualize_query
    from smra.utils.friendly_errors import (
        agent_error_answer,
        friendly_llm_message,
        friendly_rag_message,
        friendly_web_message,
        safe_agent_call,
    )
    from smra.utils.guardrails import check_input, sanitize_output
    from smra.utils.llm import call_llm
    from smra.utils.observability import get_query_id, new_query_id
    from smra.utils.schemas import expand_routes, keyword_route_fallback
except (ModuleNotFoundError, ImportError):
    from agents.rag_agent import run_rag_agent
    from agents.sql_agent import run_sql_agent
    from agents.web_agent import run_web_agent
    from cache.semantic_cache import get_cached_answer, set_cached_answer
    from router import classify_intent
    from utils.config import get_settings
    from utils.conversation import contextualize_query
    from utils.friendly_errors import (
        agent_error_answer,
        friendly_llm_message,
        friendly_rag_message,
        friendly_web_message,
        safe_agent_call,
    )
    from utils.guardrails import check_input, sanitize_output
    from utils.observability import get_query_id, new_query_id
    from utils.schemas import expand_routes, keyword_route_fallback

    from utils import audit
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
            return friendly_llm_message(exc)

    parts = []
    if sql_answer:
        parts.append(f"**Market data:** {sql_answer}")
    if rag_answer:
        parts.append(f"**Filings:** {rag_answer}")
    if parts:
        return "\n\n".join(parts)

    return "I could not retrieve enough data from market records or filings to answer that question."


def _to_urls(result: dict) -> list:
    meta = result.get("meta", {}) if isinstance(result.get("meta"), dict) else {}
    return meta.get("sources") or result.get("sources", []) or []


def _agent_answer(result: dict, agent: str) -> str:
    if not isinstance(result, dict):
        return agent_error_answer(agent, RuntimeError("invalid agent response"))
    if result.get("ok") is False:
        msg = result.get("answer") or result.get("error", {}).get("msg", "")
        if msg.strip():
            return msg
        return agent_error_answer(agent, RuntimeError("agent failed"))
    answer = (result.get("answer") or "").strip()
    if not answer:
        return agent_error_answer(agent, RuntimeError("empty agent response"))
    return answer


def _agent_ok(result: dict) -> bool:
    if not isinstance(result, dict):
        return False
    if result.get("ok") is False:
        return False
    return bool((result.get("answer") or "").strip())


def _non_empty_answer(text: str, fallback: str) -> str:
    cleaned = sanitize_output((text or "").strip())
    return cleaned if cleaned else fallback


def _run_rag_with_web_fallback(prompt: str) -> dict:
    result = safe_agent_call("RAG", run_rag_agent, prompt)
    if not isinstance(result, dict):
        return {"ok": False, "answer": friendly_rag_message(), "fallback": True}
    if not result.get("fallback"):
        return result
    web = safe_agent_call("WEB", run_web_agent, prompt)
    if isinstance(web, dict) and web.get("ok") is not False and (web.get("answer") or "").strip():
        return web
    combined = friendly_rag_message()
    if isinstance(web, dict) and web.get("ok") is False:
        combined = f"{combined} {friendly_web_message()}"
    return {**result, "ok": False, "answer": result.get("answer") or combined, "fallback": True}


def _blocked_result(query_id: str, reason: str) -> dict:
    audit.record(query_id, reason, [], f"Blocked: {reason}", ok=False)
    return {
        "query_id": query_id,
        "routes": [],
        "answer": f"Query rejected: {reason}",
        "sql": "",
        "sources": [],
        "grounded": None,
        "ok": False,
        "resolved_query": None,
    }


def answer_query(query: str, history: Optional[list[dict]] = None) -> dict[str, Any]:
    """Run the full guardrails -> contextualize -> cache -> route -> agents -> synthesize ->
    audit pipeline for one question. Returns a plain dict (not a framework-specific model)
    so any caller — FastAPI, Streamlit, the MCP server, a future CLI — can use it directly.

    `history` is optional prior turns as [{"role": "user"|"assistant", "content": str}, ...],
    oldest first; used only to resolve follow-up questions, never persisted here.
    """
    settings = get_settings()
    qid = new_query_id()
    start = time.perf_counter()

    guard = check_input(query)
    if not guard.ok:
        return _blocked_result(qid, guard.reason)

    original_prompt = guard.text
    prompt = original_prompt
    if history:
        prompt = contextualize_query(history, original_prompt)
    resolved_query = prompt if prompt != original_prompt else None

    cached = get_cached_answer(prompt)
    if cached and (cached.get("answer") or "").strip():
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        cached_answer = _non_empty_answer(cached.get("answer", ""), "Cached response was empty.")
        audit.record(
            query_id=qid,
            query=original_prompt,
            routes=cached.get("routes", []),
            answer=cached_answer,
            sql=cached.get("sql", ""),
            sources=cached.get("sources", []),
            provider=settings.llm_provider,
            latency_ms=latency_ms,
            ok=True,
        )
        return {
            "query_id": get_query_id(),
            "routes": cached.get("routes", []),
            "answer": cached_answer,
            "sql": cached.get("sql", ""),
            "sources": cached.get("sources", []),
            "grounded": cached.get("grounded"),
            "ok": True,
            "resolved_query": resolved_query,
        }

    try:
        routes = classify_intent(prompt)
    except Exception:
        logger.exception("Router failed; using keyword fallback")
        routes = keyword_route_fallback(prompt)

    execution_routes = expand_routes(routes)
    is_hybrid = "HYBRID" in routes or ("SQL" in execution_routes and "RAG" in execution_routes)

    answer = ""
    sql = ""
    sources: list = []
    grounded: Optional[bool] = None
    pipeline_ok = True

    try:
        if is_hybrid:
            sql_result = safe_agent_call("SQL", run_sql_agent, prompt)
            rag_result = _run_rag_with_web_fallback(prompt)
            pipeline_ok = _agent_ok(sql_result if isinstance(sql_result, dict) else {}) and _agent_ok(
                rag_result if isinstance(rag_result, dict) else {}
            )
            try:
                answer = synthesize_hybrid_answer(
                    prompt,
                    sql_result if isinstance(sql_result, dict) else {},
                    rag_result if isinstance(rag_result, dict) else {},
                )
            except Exception as exc:
                logger.exception("Hybrid synthesis failed")
                pipeline_ok = False
                answer = friendly_llm_message(exc)
                parts = []
                if isinstance(sql_result, dict):
                    parts.append(_agent_answer(sql_result, "SQL"))
                if isinstance(rag_result, dict):
                    parts.append(_agent_answer(rag_result, "RAG"))
                if parts:
                    answer = "\n\n".join(p for p in parts if p)
            sql = (sql_result or {}).get("sql", "") if isinstance(sql_result, dict) else ""
            sources = _to_urls(rag_result if isinstance(rag_result, dict) else {})
            grounded = (rag_result or {}).get("meta", {}).get("grounded") if isinstance(rag_result, dict) else None
        else:
            for route in execution_routes:
                if route == "SQL":
                    result = safe_agent_call("SQL", run_sql_agent, prompt)
                    answer = _agent_answer(result if isinstance(result, dict) else {}, "SQL")
                    sql = (result or {}).get("sql", "") if isinstance(result, dict) else ""
                    pipeline_ok = _agent_ok(result if isinstance(result, dict) else {})
                elif route == "RAG":
                    result = _run_rag_with_web_fallback(prompt)
                    answer = _agent_answer(result if isinstance(result, dict) else {}, "RAG")
                    sources = _to_urls(result if isinstance(result, dict) else {})
                    grounded = (result or {}).get("meta", {}).get("grounded") if isinstance(result, dict) else None
                    pipeline_ok = _agent_ok(result if isinstance(result, dict) else {})
                elif route == "WEB":
                    result = safe_agent_call("WEB", run_web_agent, prompt)
                    answer = _agent_answer(result if isinstance(result, dict) else {}, "WEB")
                    sources = _to_urls(result if isinstance(result, dict) else {})
                    pipeline_ok = _agent_ok(result if isinstance(result, dict) else {})
    except Exception as exc:
        logger.exception("Unhandled query pipeline error")
        pipeline_ok = False
        answer = agent_error_answer("LLM", exc)

    fallback_msg = "I couldn't generate an answer right now. Please try again."
    answer = _non_empty_answer(answer, fallback_msg)
    if answer == fallback_msg:
        pipeline_ok = False
    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    if pipeline_ok:
        set_cached_answer(prompt, {"routes": routes, "answer": answer, "sql": sql, "sources": sources, "grounded": grounded})

    audit.record(
        query_id=qid,
        query=original_prompt,
        routes=routes,
        answer=answer,
        sql=sql,
        sources=sources,
        provider=settings.llm_provider,
        latency_ms=latency_ms,
        ok=pipeline_ok,
    )

    return {
        "query_id": get_query_id(),
        "routes": routes,
        "answer": answer,
        "sql": sql,
        "sources": sources,
        "grounded": grounded,
        "ok": pipeline_ok,
        "resolved_query": resolved_query,
    }
