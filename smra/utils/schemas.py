from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
import json
import re


@dataclass
class AgentResponse:
    ok: bool
    answer: str = ""
    data: Any = None
    meta: Dict[str, Any] = field(default_factory=dict)
    fallback: bool = False
    error: Dict[str, Any] = field(default_factory=dict)


def success_response(answer: str, data: Any = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return a dict matching the AgentResponse success schema."""
    resp = AgentResponse(ok=True, answer=answer, data=data, meta=meta or {}, fallback=False, error={})
    return asdict(resp)


def error_response(msg: str, error_type: str = "exec", fallback: bool = True) -> Dict[str, Any]:
    """Return a dict matching the AgentResponse error schema.

    error_type should be one of: 'llm', 'exec', 'io'
    """
    resp = AgentResponse(ok=False, answer="", data=None, meta={}, fallback=fallback, error={"msg": msg, "type": error_type})
    return asdict(resp)


def validate_router_output(raw: str) -> List[str]:
    """Safely extract router intent from arbitrary LLM output.

    Attempts JSON parse first, then regex extraction. Returns one of:
    - ["SQL"], ["RAG"], ["WEB"] or ["HYBRID"] (if both SQL and RAG present)
    Falls back to ['SQL'] as the safe default.
    """
    if not raw:
        return ["SQL"]

    # strip common fences and surrounding text
    s = raw.strip()
    s = s.replace("```json", "").replace("```", "")

    # Try JSON first
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
            tokens = [t for t in tokens if t in {"SQL", "RAG", "WEB"}]
            if "SQL" in tokens and "RAG" in tokens:
                return ["HYBRID"]
            if tokens:
                return [tokens[0]] if len(tokens) == 1 else tokens
    except Exception:
        pass

    # Fallback: look for explicit keywords in the text
    up = s.upper()
    found = []
    for t in ("SQL", "RAG", "WEB"):
        if re.search(rf"\b{t}\b", up):
            found.append(t)
    if "SQL" in found and "RAG" in found:
        return ["HYBRID"]
    if found:
        return [found[0]] if len(found) == 1 else found

    # Final safe default
    return ["SQL"]
