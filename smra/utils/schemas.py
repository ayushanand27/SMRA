import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

VALID_ROUTES = frozenset({"SQL", "RAG", "WEB", "HYBRID"})


@dataclass
class AgentResponse:
    ok: bool
    answer: str = ""
    data: Any = None
    meta: Dict[str, Any] = field(default_factory=dict)
    fallback: bool = False
    error: Dict[str, Any] = field(default_factory=dict)
    sql: str = ""


def success_response(
    answer: str,
    data: Any = None,
    meta: Optional[Dict[str, Any]] = None,
    sql: str = "",
) -> Dict[str, Any]:
    """Return a dict matching the AgentResponse success schema."""
    resp = AgentResponse(
        ok=True,
        answer=answer,
        data=data,
        meta=meta or {},
        fallback=False,
        error={},
        sql=sql,
    )
    return asdict(resp)


def error_response(msg: str, error_type: str = "exec", fallback: bool = True, sql: str = "") -> Dict[str, Any]:
    """Return a dict matching the AgentResponse error schema."""
    resp = AgentResponse(
        ok=False,
        answer="",
        data=None,
        meta={},
        fallback=fallback,
        error={"msg": msg, "type": error_type},
        sql=sql,
    )
    return asdict(resp)


def _normalize_route_tokens(tokens: List[str]) -> List[str]:
    """Collapse SQL+RAG pairs into HYBRID; drop unknown tokens."""
    cleaned = [t for t in tokens if t in VALID_ROUTES]
    if "HYBRID" in cleaned:
        return ["HYBRID"]
    if "SQL" in cleaned and "RAG" in cleaned:
        return ["HYBRID"]
    # preserve order, dedupe
    seen: set[str] = set()
    out: List[str] = []
    for t in cleaned:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def validate_router_output(raw: str) -> List[str]:
    """Safely extract router intent from arbitrary LLM output."""
    if not raw:
        return ["SQL"]

    s = raw.strip().replace("```json", "").replace("```", "")

    match = re.search(r"\{.*?\}", s, re.DOTALL)
    if match:
        s = match.group()

    try:
        parsed = json.loads(s)
        if isinstance(parsed, dict):
            route = parsed.get("route") or parsed.get("routes") or parsed.get("agent")
            if isinstance(route, (list, tuple)):
                tokens = [str(x).upper() for x in route]
            elif isinstance(route, str):
                tokens = [t.strip().upper() for t in re.split(r"[,;\s]+", route) if t.strip()]
            else:
                tokens = []
            normalized = _normalize_route_tokens(tokens)
            if normalized:
                return normalized
    except Exception:
        pass

    up = s.upper()
    found = []
    for t in ("SQL", "RAG", "WEB"):
        if re.search(rf"\b{t}\b", up):
            found.append(t)
    normalized = _normalize_route_tokens(found)
    if normalized:
        return normalized

    return ["SQL"]


def expand_routes(routes: List[str]) -> List[str]:
    """Expand HYBRID into concrete agent routes for execution."""
    expanded: List[str] = []
    for route in routes:
        if route == "HYBRID":
            for agent in ("SQL", "RAG"):
                if agent not in expanded:
                    expanded.append(agent)
        elif route in {"SQL", "RAG", "WEB"} and route not in expanded:
            expanded.append(route)
    return expanded or ["SQL"]


def keyword_route_fallback(query: str) -> List[str]:
    """Deterministic router fallback when the LLM is unavailable."""
    q = query.lower()
    if any(w in q for w in ("news", "latest", "today", "why", "recent", "analyst")):
        return ["WEB"]
    has_sql = any(
        w in q
        for w in ("price", "volume", "close", "open", "moving average", "ohlc", "stock", "sector performance")
    )
    has_rag = any(
        w in q
        for w in (
            "revenue",
            "sales",
            "earnings",
            "profit",
            "filing",
            "annual",
            "10-k",
            "income",
            "margin",
            "balance sheet",
            "cash flow",
            "financial statement",
            "guidance",
            "r&d",
        )
    )
    if has_sql and has_rag:
        return ["HYBRID"]
    if has_rag:
        return ["RAG"]
    return ["SQL"]
