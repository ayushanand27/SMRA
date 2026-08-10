"""FastAPI service exposing SMRA agents as an HTTP API.

This makes the agents usable outside Streamlit (CLI, bots, CI evals, other apps)
and provides a clean audited entry point. Run with:

    uvicorn smra.api:app --reload --port 8000
"""
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, List, Optional

from dotenv import load_dotenv

_SMRA_ROOT = Path(__file__).resolve().parent
_env_path = _SMRA_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=True)
else:
    load_dotenv(override=True)

from fastapi import Depends, FastAPI, Header, HTTPException, Request  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

try:
    from smra.agents.rag_agent import run_rag_agent
    from smra.agents.sql_agent import run_sql_agent
    from smra.agents.web_agent import run_web_agent
    from smra.cache.semantic_cache import get_cached_answer, set_cached_answer
    from smra.orchestrator import synthesize_hybrid_answer
    from smra.router import classify_intent
    from smra.utils import audit
    from smra.utils.config import get_settings
    from smra.utils.friendly_errors import (
        agent_error_answer,
        friendly_llm_message,
        friendly_rag_message,
        friendly_web_message,
        safe_agent_call,
    )
    from smra.utils.guardrails import check_input, sanitize_output
    from smra.utils.observability import configure_logging, get_query_id, new_query_id
    from smra.utils.schemas import expand_routes
    from smra.utils.security import check_rate_limit, verify_api_key
except (ModuleNotFoundError, ImportError):
    from agents.rag_agent import run_rag_agent
    from agents.sql_agent import run_sql_agent
    from agents.web_agent import run_web_agent
    from cache.semantic_cache import get_cached_answer, set_cached_answer
    from orchestrator import synthesize_hybrid_answer
    from router import classify_intent
    from utils.config import get_settings
    from utils.friendly_errors import (
        agent_error_answer,
        friendly_llm_message,
        friendly_rag_message,
        friendly_web_message,
        safe_agent_call,
    )
    from utils.guardrails import check_input, sanitize_output
    from utils.observability import configure_logging, get_query_id, new_query_id
    from utils.schemas import expand_routes
    from utils.security import check_rate_limit, verify_api_key

    from utils import audit

logger = logging.getLogger("smra.api")

settings = get_settings()
configure_logging(level=settings.log_level, json_logs=settings.json_logs)

try:
    from smra.utils.config import validate_production_config
except (ModuleNotFoundError, ImportError):
    from utils.config import validate_production_config

validate_production_config(settings)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start/stop background ingestion with the API process."""
    try:
        from smra.ingestion.scheduler import start_scheduler, stop_scheduler
        from smra.utils.warmup import run_warmup
    except (ModuleNotFoundError, ImportError):
        from ingestion.scheduler import start_scheduler, stop_scheduler
        from utils.warmup import run_warmup

    run_warmup(background=True)
    start_scheduler()
    yield
    stop_scheduler()


app = FastAPI(
    title="SMRA API",
    description="Stock Market Research Assistant — RAG + Text-to-SQL + Web search",
    version="0.5.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-API-Key"],
)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    return response


def auth_and_limit(request: Request, x_api_key: Optional[str] = Header(default=None)) -> str:
    """FastAPI dependency: enforce API-key auth and per-identity rate limiting."""
    if not verify_api_key(x_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing API key (X-API-Key).")

    identity = x_api_key or (request.client.host if request.client else "anonymous")
    allowed, retry_after = check_rate_limit(identity)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail="Rate limit exceeded. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )
    return identity


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural language question")


class QueryResponse(BaseModel):
    query_id: str
    routes: List[str]
    answer: str
    sql: str = ""
    sources: List[Any] = []
    grounded: Optional[bool] = None
    ok: bool = True


def _to_urls(result: dict) -> list:
    meta = result.get("meta", {}) if isinstance(result.get("meta"), dict) else {}
    return meta.get("sources") or result.get("sources", []) or []


@app.get("/health")
def health() -> dict:
    try:
        from smra.utils.config import is_mock_mode
    except (ModuleNotFoundError, ImportError):
        from utils.config import is_mock_mode

    return {
        "status": "ok",
        "provider": settings.llm_provider,
        "mock_mode": is_mock_mode(),
        "ingestion_enabled": settings.ingestion_enabled,
        "postgres": bool(settings.database_url),
    }


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
    if cleaned:
        return cleaned
    return fallback


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


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest, _identity: str = Depends(auth_and_limit)) -> QueryResponse:
    qid = new_query_id()
    start = time.perf_counter()

    guard = check_input(req.query)
    if not guard.ok:
        audit.record(qid, req.query, [], f"Blocked: {guard.reason}", ok=False)
        return QueryResponse(query_id=qid, routes=[], answer=f"Query rejected: {guard.reason}", ok=False)

    prompt = guard.text

    cached = get_cached_answer(prompt)
    if cached and (cached.get("answer") or "").strip():
        latency_ms = round((time.perf_counter() - start) * 1000, 2)
        cached_answer = _non_empty_answer(cached.get("answer", ""), "Cached response was empty.")
        audit.record(
            query_id=qid,
            query=prompt,
            routes=cached.get("routes", []),
            answer=cached_answer,
            sql=cached.get("sql", ""),
            sources=cached.get("sources", []),
            provider=settings.llm_provider,
            latency_ms=latency_ms,
            ok=True,
        )
        return QueryResponse(
            query_id=get_query_id(),
            routes=cached.get("routes", []),
            answer=cached_answer,
            sql=cached.get("sql", ""),
            sources=cached.get("sources", []),
            grounded=cached.get("grounded"),
            ok=True,
        )

    try:
        routes = classify_intent(prompt)
    except Exception:
        logger.exception("Router failed; using keyword fallback")
        try:
            from smra.utils.schemas import keyword_route_fallback
        except (ModuleNotFoundError, ImportError):
            from utils.schemas import keyword_route_fallback
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

    payload = {
        "routes": routes,
        "answer": answer,
        "sql": sql,
        "sources": sources,
        "grounded": grounded,
    }
    if pipeline_ok:
        set_cached_answer(prompt, payload)

    audit.record(
        query_id=qid,
        query=prompt,
        routes=routes,
        answer=answer,
        sql=sql,
        sources=sources,
        provider=settings.llm_provider,
        latency_ms=latency_ms,
        ok=pipeline_ok,
    )

    return QueryResponse(
        query_id=get_query_id(),
        routes=routes,
        answer=answer,
        sql=sql,
        sources=sources,
        grounded=grounded,
        ok=pipeline_ok,
    )


@app.get("/audit")
def audit_recent(limit: int = 20, _identity: str = Depends(auth_and_limit)) -> dict:
    return {"records": audit.recent(limit=limit)}
