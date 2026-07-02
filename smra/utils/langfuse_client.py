"""Optional Langfuse integration for managed LLM tracing.

Enabled only when LANGFUSE_ENABLED=1 and keys are present. Everything degrades
to a no-op if the SDK is missing or misconfigured, so the app never breaks.
Provides a context manager to record a generation (prompt/response/model/usage).
"""
import logging
from contextlib import contextmanager

try:
    from smra.utils.config import get_settings
except (ModuleNotFoundError, ImportError):
    from utils.config import get_settings

logger = logging.getLogger("smra.langfuse")

_client = None
_init_failed = False


def get_client():
    """Lazily construct the Langfuse client; returns None when disabled/unavailable."""
    global _client, _init_failed
    if _client is not None or _init_failed:
        return _client

    settings = get_settings()
    if not settings.langfuse_enabled:
        _init_failed = True
        return None
    if not (settings.langfuse_public_key and settings.langfuse_secret_key):
        logger.info("Langfuse enabled but keys missing; skipping")
        _init_failed = True
        return None

    try:
        from langfuse import Langfuse

        _client = Langfuse(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
        )
        logger.info("Langfuse client initialized (host=%s)", settings.langfuse_host)
    except Exception:
        logger.info("Langfuse SDK unavailable; tracing disabled")
        _init_failed = True
    return _client


@contextmanager
def observe_generation(name: str, model: str, provider: str, prompt: str):
    """Record one LLM generation to Langfuse when available; no-op otherwise.

    Usage:
        with observe_generation("router", model, provider, user_prompt) as gen:
            output = call(...)
            gen["output"] = output
            gen["input_tokens"] = 12
    """
    holder: dict = {"output": "", "input_tokens": 0, "output_tokens": 0}
    client = get_client()
    if client is None:
        yield holder
        return

    trace = None
    try:
        trace = client.trace(name=name, input=prompt[:2000])
    except Exception:
        logger.debug("Langfuse trace creation failed", exc_info=True)

    try:
        yield holder
    finally:
        try:
            if trace is not None:
                trace.generation(
                    name=name,
                    model=model,
                    metadata={"provider": provider},
                    input=prompt[:2000],
                    output=str(holder.get("output", ""))[:4000],
                    usage={
                        "input": holder.get("input_tokens", 0),
                        "output": holder.get("output_tokens", 0),
                    },
                )
                if hasattr(client, "flush"):
                    client.flush()
        except Exception:
            logger.debug("Langfuse generation logging failed", exc_info=True)
