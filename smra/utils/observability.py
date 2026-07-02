"""Lightweight observability: structured logs, latency, token & cost tracking.

Follows the spirit of the OpenTelemetry GenAI conventions without requiring the
full OTel stack. Emits structured records for each LLM call (provider, model,
latency_ms, token counts, estimated cost, finish reason, error type) and
supports a per-request correlation id (query_id).
"""
import contextvars
import json
import logging
import time
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field

logger = logging.getLogger("smra.observability")

# Correlation id shared across a single user request lifecycle.
_query_id: contextvars.ContextVar[str] = contextvars.ContextVar("smra_query_id", default="")

# Approx USD per 1M tokens (input, output). Best-effort estimates; override via env if needed.
_PRICING: dict[str, tuple[float, float]] = {
    "mixtral-8x7b-32768": (0.24, 0.24),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-1.5-pro": (1.25, 5.00),
}


def new_query_id() -> str:
    qid = uuid.uuid4().hex[:12]
    _query_id.set(qid)
    return qid


def get_query_id() -> str:
    return _query_id.get()


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price = _PRICING.get(model)
    if not price:
        return 0.0
    in_rate, out_rate = price
    return round((input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate, 6)


@dataclass
class LLMCallRecord:
    event: str = "llm_call"
    query_id: str = ""
    provider: str = ""
    model: str = ""
    latency_ms: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    estimated_cost_usd: float = 0.0
    finish_reason: str = ""
    error_type: str = ""
    ok: bool = True
    extra: dict = field(default_factory=dict)


def log_llm_call(record: LLMCallRecord) -> None:
    record.query_id = record.query_id or get_query_id()
    record.total_tokens = record.input_tokens + record.output_tokens
    payload = {k: v for k, v in asdict(record).items() if v not in ("", 0, 0.0, {}) or k in ("ok", "event")}
    logger.info(json.dumps(payload, default=str))


@contextmanager
def track_llm_call(provider: str, model: str):
    """Context manager that times an LLM call and emits a structured record.

    Usage:
        with track_llm_call("groq", model) as rec:
            resp = client.create(...)
            rec.input_tokens = resp.usage.prompt_tokens
            rec.output_tokens = resp.usage.completion_tokens
            rec.finish_reason = resp.choices[0].finish_reason
    """
    rec = LLMCallRecord(provider=provider, model=model, query_id=get_query_id())
    start = time.perf_counter()
    try:
        yield rec
        rec.ok = True
    except Exception as exc:
        rec.ok = False
        rec.error_type = type(exc).__name__
        raise
    finally:
        rec.latency_ms = round((time.perf_counter() - start) * 1000, 2)
        if not rec.estimated_cost_usd:
            rec.estimated_cost_usd = estimate_cost_usd(model, rec.input_tokens, rec.output_tokens)
        log_llm_call(rec)


class JsonLogFormatter(logging.Formatter):
    """Optional JSON log formatter for production log aggregation."""

    def format(self, record: logging.LogRecord) -> str:
        base = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        qid = get_query_id()
        if qid:
            base["query_id"] = qid
        if record.exc_info:
            base["exc"] = self.formatException(record.exc_info)
        return json.dumps(base, default=str)


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    root = logging.getLogger()
    root.setLevel(level.upper())
    handler = logging.StreamHandler()
    if json_logs:
        handler.setFormatter(JsonLogFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.handlers.clear()
    root.addHandler(handler)
