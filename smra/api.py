"""FastAPI service exposing SMRA agents as an HTTP API.

This makes the agents usable outside Streamlit (CLI, bots, CI evals, other apps)
and provides a clean audited entry point. Run with:

    uvicorn smra.api:app --reload --port 8000
"""
import logging
import time
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
from pydantic import BaseModel, Field  # noqa: E402

try:
    from smra.agents.rag_agent import run_rag_agent
    from smra.agents.sql_agent import run_sql_agent
    from smra.agents.web_agent import run_web_agent
    from smra.orchestrator import synthesize_hybrid_answer
    from smra.router import classify_intent
    from smra.utils import audit
    from smra.utils.config import get_settings
    from smra.utils.guardrails import check_input, sanitize_output
    from smra.utils.observability import configure_logging, get_query_id, new_query_id
    from smra.utils.schemas import expand_routes
    from smra.utils.security import check_rate_limit, verify_api_key
except (ModuleNotFoundError, ImportError):
    from agents.rag_agent import run_rag_agent
    from agents.sql_agent import run_sql_agent
    from agents.web_agent import run_web_agent
    from orchestrator import synthesize_hybrid_answer
    from router import classify_intent
    from utils.config import get_settings
    from utils.guardrails import check_input, sanitize_output
    from utils.observability import configure_logging, get_query_id, new_query_id
    from utils.schemas import expand_routes
    from utils.security import check_rate_limit, verify_api_key

    from utils import audit

logger = logging.getLogger("smra.api")

settings = get_settings()
configure_logging(level=settings.log_level, json_logs=settings.json_logs)

app = FastAPI(
    title="SMRA API",
    description="Stock Market Research Assistant — RAG + Text-to-SQL + Web search",
    version="0.4.0",
)


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
    return {"status": "ok", "provider": settings.llm_provider}


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest, _identity: str = Depends(auth_and_limit)) -> QueryResponse:
    qid = new_query_id()
    start = time.perf_counter()

    guard = check_input(req.query)
    if not guard.ok:
        audit.record(qid, req.query, [], f"Blocked: {guard.reason}", ok=False)
        return QueryResponse(query_id=qid, routes=[], answer=f"Query rejected: {guard.reason}", ok=False)

    prompt = guard.text
    routes = classify_intent(prompt)
    execution_routes = expand_routes(routes)
    is_hybrid = "HYBRID" in routes or ("SQL" in execution_routes and "RAG" in execution_routes)

    answer = ""
    sql = ""
    sources: list = []
    grounded: Optional[bool] = None

    if is_hybrid:
        sql_result = run_sql_agent(prompt)
        rag_result = run_rag_agent(prompt)
        if isinstance(rag_result, dict) and rag_result.get("fallback"):
            rag_result = run_web_agent(prompt)
        answer = synthesize_hybrid_answer(prompt, sql_result, rag_result)
        sql = sql_result.get("sql", "")
        sources = _to_urls(rag_result)
        grounded = rag_result.get("meta", {}).get("grounded")
    else:
        for route in execution_routes:
            if route == "SQL":
                result = run_sql_agent(prompt)
                answer = result.get("answer", "")
                sql = result.get("sql", "")
            elif route == "RAG":
                result = run_rag_agent(prompt)
                if isinstance(result, dict) and result.get("fallback"):
                    result = run_web_agent(prompt)
                answer = result.get("answer", "")
                sources = _to_urls(result)
                grounded = result.get("meta", {}).get("grounded")
            elif route == "WEB":
                result = run_web_agent(prompt)
                answer = result.get("answer", "")
                sources = _to_urls(result)

    answer = sanitize_output(answer)
    latency_ms = round((time.perf_counter() - start) * 1000, 2)

    audit.record(
        query_id=qid,
        query=prompt,
        routes=routes,
        answer=answer,
        sql=sql,
        sources=sources,
        provider=settings.llm_provider,
        latency_ms=latency_ms,
        ok=True,
    )

    return QueryResponse(
        query_id=get_query_id(),
        routes=routes,
        answer=answer,
        sql=sql,
        sources=sources,
        grounded=grounded,
        ok=True,
    )


@app.get("/audit")
def audit_recent(limit: int = 20, _identity: str = Depends(auth_and_limit)) -> dict:
    return {"records": audit.recent(limit=limit)}
