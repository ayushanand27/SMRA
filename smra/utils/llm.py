import hashlib
import json
import logging
import os
import re
import time

try:
    from smra.utils.config import get_settings, is_mock_mode
    from smra.utils.langfuse_client import observe_generation
    from smra.utils.observability import track_llm_call
except (ModuleNotFoundError, ImportError):
    from utils.config import get_settings, is_mock_mode
    from utils.langfuse_client import observe_generation
    from utils.observability import track_llm_call

logger = logging.getLogger("smra.llm")

_mock_mode_logged = False


def _log_mock_mode_once() -> None:
    global _mock_mode_logged
    if _mock_mode_logged:
        return
    _mock_mode_logged = True
    logger.warning(
        "*** MOCK_MODE active — LLM responses are synthetic (no Groq/Ollama/Gemini calls) ***"
    )


def _mock_route_json(user_prompt: str) -> str:
    q = user_prompt.lower()
    if any(w in q for w in ("news", "latest", "today", "recent", "forecast")):
        return '{"route": ["WEB"]}'
    rag = any(w in q for w in ("revenue", "sales", "filing", "10-k", "annual", "earnings", "report"))
    sql = any(
        w in q
        for w in ("price", "close", "closing", "volume", "marketcap", "market cap", "stock", "aapl")
    )
    if rag and sql:
        return '{"route": ["SQL", "RAG"]}'
    if rag:
        return '{"route": ["RAG"]}'
    return '{"route": ["SQL"]}'


def _mock_sql(user_prompt: str) -> str:
    q = user_prompt.lower()
    if "marketcap" in q or "market cap" in q or "top" in q and "stock" in q:
        return (
            "SELECT symbol, company, marketcap, currency FROM stock_prices "
            "WHERE currency = 'USD' ORDER BY marketcap DESC LIMIT 5"
        )
    if "reliance" in q:
        return (
            "SELECT symbol, date, close, currency FROM stock_prices "
            "WHERE symbol = 'RELIANCE.NS' ORDER BY date DESC LIMIT 5"
        )
    if "nvidia" in q or "nvda" in q:
        return (
            "SELECT symbol, date, close, currency FROM stock_prices "
            "WHERE symbol = 'NVDA' ORDER BY date DESC LIMIT 5"
        )
    if "2025-01-02" in user_prompt:
        return (
            "SELECT symbol, date, close, currency FROM stock_prices "
            "WHERE symbol = 'AAPL' AND date = '2025-01-02' ORDER BY date"
        )
    return (
        "SELECT symbol, date, close, currency FROM stock_prices "
        "WHERE symbol = 'AAPL' ORDER BY date DESC LIMIT 10"
    )


def _call_mock(system_prompt: str, user_prompt: str, model: str, max_tokens: int, temperature: float) -> str:
    """Fast deterministic stub for infra load tests and CI (MOCK_MODE=1 only)."""
    _log_mock_mode_once()
    sys_l = (system_prompt or "").lower()
    user_l = (user_prompt or "").lower()

    with track_llm_call("mock", model) as rec:
        rec.input_tokens = max(1, len(user_prompt) // 4)
        rec.output_tokens = 64
        rec.finish_reason = "stop"

        if "query router" in sys_l or user_prompt.strip().lower().startswith("query:"):
            return _mock_route_json(user_l)

        if "rewrite the user's query" in user_l or "rewritten search phrase" in user_l:
            if "apple" in user_l or "aapl" in user_l:
                return "Apple Inc total net sales annual report 10-K"
            if "nvidia" in user_l:
                return "NVIDIA revenue annual filing 10-K"
            return user_prompt.split("User query:")[-1].split("\n")[0].strip() or "financial filing search"

        if "expert sql" in sys_l or "sql query writer" in sys_l or "question:" in user_l:
            return _mock_sql(user_prompt)

        if "financial news analyst" in sys_l and "json" in sys_l:
            return json.dumps(
                {
                    "answer": "[MOCK] Recent headlines indicate mixed sentiment for the queried topic.",
                    "sentiment": {"label": "Neutral", "score": 0.5},
                    "symbols": ["AAPL"],
                }
            )

        if "hybrid" in sys_l or ("sql" in user_l and "rag" in user_l):
            return (
                "[MOCK] Combined view: AAPL closed near $178 USD; filing revenue figures "
                "are available in the annual report context."
            )

        if "financial analyst" in sys_l or "ocr-extracted" in sys_l or "filing" in sys_l:
            return (
                "[MOCK] Based on the retrieved filing excerpt, total net sales were "
                "approximately 383,285 million USD."
            )

        digest = hashlib.sha256((system_prompt + user_prompt).encode()).hexdigest()[:8]
        return f"[MOCK] Deterministic stub response ({digest})."


def _call_groq(system_prompt: str, user_prompt: str, model: str, max_tokens: int, temperature: float) -> str:
    from groq import Groq

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    settings = get_settings()

    max_retries = 5
    wait_seconds = 3
    last_exc = None
    is_gpt_oss = "gpt-oss" in (model or "").lower()

    for attempt in range(1, max_retries + 1):
        try:
            with track_llm_call("groq", model) as rec:
                kwargs = {
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt or "You are a helpful assistant."},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                }
                # Reasoning models burn completion budget on chain-of-thought unless effort is low.
                # Older groq SDKs reject reasoning_* kwargs — pass via extra_body.
                if is_gpt_oss:
                    effort = settings.groq_reasoning_effort
                    if effort in {"low", "medium", "high"}:
                        kwargs["extra_body"] = {
                            "reasoning_effort": effort,
                            "include_reasoning": False,
                        }

                response = client.chat.completions.create(**kwargs)
                usage = getattr(response, "usage", None)
                if usage is not None:
                    rec.input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                    rec.output_tokens = getattr(usage, "completion_tokens", 0) or 0
                choice = response.choices[0]
                rec.finish_reason = getattr(choice, "finish_reason", "") or ""
                # openai/gpt-oss-* may spend completion budget on `reasoning` and leave
                # content empty when max_tokens is too low (finish_reason=length).
                content = getattr(choice.message, "content", None) or ""
                if not str(content).strip() and rec.finish_reason == "length" and attempt < max_retries:
                    raise RuntimeError(
                        "empty_content_after_reasoning_budget; retry with higher max_tokens"
                    )
                return str(content)

        except Exception as exc:
            last_exc = exc
            err_str = str(exc).lower()
            logger.warning("Groq attempt %s failed: %s", attempt, err_str[:120])

            # Auth failures are not transient — fail fast instead of 5× retry (~40s).
            if any(
                token in err_str
                for token in ("401", "403", "invalid api key", "invalid_api_key", "authentication")
            ):
                break

            if "empty_content_after_reasoning_budget" in err_str:
                max_tokens = min(max(max_tokens * 2, 2500), 8000)
                logger.info("Raising max_tokens to %s for gpt-oss reasoning headroom", max_tokens)
                wait = 0.5

            match = re.search(r"try again in (\d+(?:\.\d+)?)s", err_str)
            if "empty_content_after_reasoning_budget" not in err_str:
                wait = float(match.group(1)) + 1 if match else wait_seconds
            else:
                wait = 0.5

            if attempt < max_retries:
                logger.info("Waiting %ss before retry...", wait)
                time.sleep(wait)

    raise RuntimeError(f"Groq failed after {max_retries} retries: {last_exc}")


def _call_ollama(system_prompt: str, user_prompt: str, model: str, max_tokens: int, temperature: float) -> str:
    import requests

    settings = get_settings()
    base_url = settings.ollama_url.rstrip("/")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt or "You are a helpful assistant."},
            {"role": "user", "content": user_prompt},
        ],
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    with track_llm_call("ollama", model) as rec:
        response = requests.post(f"{base_url}/api/chat", json=payload, timeout=120)
        response.raise_for_status()
        data = response.json()
        rec.input_tokens = data.get("prompt_eval_count", 0) or 0
        rec.output_tokens = data.get("eval_count", 0) or 0
        rec.finish_reason = data.get("done_reason", "") or ""
        return data["message"]["content"]


def _call_gemini(system_prompt: str, user_prompt: str, model: str, max_tokens: int, temperature: float) -> str:
    import google.generativeai as genai

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY is required when LLM_PROVIDER=gemini")

    genai.configure(api_key=api_key)
    gen_model = genai.GenerativeModel(model, system_instruction=system_prompt or None)
    with track_llm_call("gemini", model) as rec:
        response = gen_model.generate_content(
            user_prompt,
            generation_config={"temperature": temperature, "max_output_tokens": max_tokens},
        )
        usage = getattr(response, "usage_metadata", None)
        if usage is not None:
            rec.input_tokens = getattr(usage, "prompt_token_count", 0) or 0
            rec.output_tokens = getattr(usage, "candidates_token_count", 0) or 0
        return response.text


def call_llm(system_prompt: str, user_prompt: str, max_tokens: int | None = None, temperature: float | None = None) -> str:
    """Unified LLM entry point selected via LLM_PROVIDER (groq | ollama | gemini | mock).

    When MOCK_MODE=1 or LLM_PROVIDER=mock, returns fast deterministic stubs (no external LLM APIs).
    """
    settings = get_settings()
    max_tokens = settings.llm_max_tokens if max_tokens is None else max_tokens
    temperature = settings.llm_temperature if temperature is None else temperature

    if is_mock_mode():
        model = "mock-stub"
        provider = "mock"
        fn = _call_mock
    elif settings.llm_provider == "groq":
        model = settings.groq_model
        provider = "groq"
        fn = _call_groq
    elif settings.llm_provider == "ollama":
        model = settings.ollama_model
        provider = "ollama"
        fn = _call_ollama
    elif settings.llm_provider == "gemini":
        model = settings.gemini_model
        provider = "gemini"
        fn = _call_gemini
    else:
        raise ValueError(
            f"Unsupported LLM_PROVIDER '{settings.llm_provider}'. "
            "Use groq, ollama, gemini, or mock (with MOCK_MODE=1)."
        )

    with observe_generation(name="call_llm", model=model, provider=provider, prompt=user_prompt) as gen:
        output = fn(system_prompt, user_prompt, model, max_tokens, temperature)
        gen["output"] = output
        return output
