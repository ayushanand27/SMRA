"""FastAPI service exposing SMRA agents as an HTTP API.

This makes the agents usable outside Streamlit (CLI, bots, CI evals, other apps)
and provides a clean audited entry point. Run with:

    uvicorn smra.api:app --reload --port 8000
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, List, Literal, Optional

from dotenv import load_dotenv

_SMRA_ROOT = Path(__file__).resolve().parent
_env_path = _SMRA_ROOT / ".env"
if _env_path.exists():
    load_dotenv(_env_path, override=True)
else:
    load_dotenv(override=True)

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from pydantic import BaseModel, Field  # noqa: E402

try:
    from smra.orchestrator import answer_query
    from smra.utils import audit
    from smra.utils.config import get_settings
    from smra.utils.db import scalar_query
    from smra.utils.observability import configure_logging
    from smra.utils.security import _get_redis_client, check_rate_limit, verify_api_key
except (ModuleNotFoundError, ImportError):
    from orchestrator import answer_query
    from utils.config import get_settings
    from utils.db import scalar_query
    from utils.observability import configure_logging
    from utils.security import _get_redis_client, check_rate_limit, verify_api_key

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


class Turn(BaseModel):
    """One prior message in the conversation, as the client remembers it.

    Stateless by design: the client (Streamlit session, external caller) owns
    conversation history and resends it each turn — no server-side session
    store, so this works the same for one API replica or many.
    """

    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="Natural language question")
    history: List[Turn] = Field(
        default_factory=list,
        max_length=12,
        description="Recent conversation turns (oldest first), for resolving follow-up questions "
        "like 'what about last year?'. Only the most recent turns are actually used.",
    )


class QueryResponse(BaseModel):
    query_id: str
    routes: List[str]
    answer: str
    sql: str = ""
    sources: List[Any] = []
    grounded: Optional[bool] = None
    ok: bool = True
    resolved_query: Optional[str] = None
    """Set only when history changed how the query was interpreted, e.g. 'what about last year?'
    resolved to 'What was AAPL revenue in 2025?' — lets a client show what was actually asked."""


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


@app.get("/health/ready")
def health_ready(response: Response) -> dict:
    """Readiness probe: actually pings Postgres and Redis instead of checking config presence.

    Use /health for a cheap liveness check; use this before routing real traffic to an
    instance (e.g. behind a load balancer) since a query can still fail even when the
    process is up if the DB or Redis is unreachable.
    """
    checks: dict[str, Any] = {}

    if settings.database_url:
        try:
            scalar_query("SELECT 1")
            checks["postgres"] = "ok"
        except Exception as exc:
            checks["postgres"] = f"error: {exc}"[:200]
    else:
        checks["postgres"] = "not_configured (using SQLite fallback)"

    if settings.rate_limit_enabled:
        try:
            client = _get_redis_client()
            checks["redis"] = "ok" if client is not None else "unreachable (using in-memory fallback)"
        except Exception as exc:
            checks["redis"] = f"error: {exc}"[:200]
    else:
        checks["redis"] = "disabled"

    hard_failure = isinstance(checks.get("postgres"), str) and checks["postgres"].startswith("error:")
    response.status_code = 503 if hard_failure else 200
    return {"ready": not hard_failure, "checks": checks}


@app.post("/query", response_model=QueryResponse)
def query(req: QueryRequest, _identity: str = Depends(auth_and_limit)) -> QueryResponse:
    history = [t.model_dump() for t in req.history] if req.history else None
    result = answer_query(req.query, history=history)
    return QueryResponse(**result)


@app.get("/audit")
def audit_recent(limit: int = 20, _identity: str = Depends(auth_and_limit)) -> dict:
    return {"records": audit.recent(limit=limit)}
