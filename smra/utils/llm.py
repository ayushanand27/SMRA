import logging
import os
import re
import time

try:
    from smra.utils.config import get_settings
    from smra.utils.langfuse_client import observe_generation
    from smra.utils.observability import track_llm_call
except (ModuleNotFoundError, ImportError):
    from utils.config import get_settings
    from utils.langfuse_client import observe_generation
    from utils.observability import track_llm_call

logger = logging.getLogger("smra.llm")


def _call_groq(system_prompt: str, user_prompt: str, model: str, max_tokens: int, temperature: float) -> str:
    from groq import Groq

    client = Groq(api_key=os.getenv("GROQ_API_KEY"))

    max_retries = 5
    wait_seconds = 3
    last_exc = None

    for attempt in range(1, max_retries + 1):
        try:
            with track_llm_call("groq", model) as rec:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt or "You are a helpful assistant."},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                )
                usage = getattr(response, "usage", None)
                if usage is not None:
                    rec.input_tokens = getattr(usage, "prompt_tokens", 0) or 0
                    rec.output_tokens = getattr(usage, "completion_tokens", 0) or 0
                rec.finish_reason = getattr(response.choices[0], "finish_reason", "") or ""
                return response.choices[0].message.content

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

            match = re.search(r"try again in (\d+(?:\.\d+)?)s", err_str)
            wait = float(match.group(1)) + 1 if match else wait_seconds

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
    """Unified LLM entry point selected via LLM_PROVIDER (groq | ollama | gemini)."""
    settings = get_settings()
    provider = settings.llm_provider
    max_tokens = settings.llm_max_tokens if max_tokens is None else max_tokens
    temperature = settings.llm_temperature if temperature is None else temperature

    if provider == "groq":
        model = settings.groq_model
        fn = _call_groq
    elif provider == "ollama":
        model = settings.ollama_model
        fn = _call_ollama
    elif provider == "gemini":
        model = settings.gemini_model
        fn = _call_gemini
    else:
        raise ValueError(f"Unsupported LLM_PROVIDER '{provider}'. Use groq, ollama, or gemini.")

    with observe_generation(name="call_llm", model=model, provider=provider, prompt=user_prompt) as gen:
        output = fn(system_prompt, user_prompt, model, max_tokens, temperature)
        gen["output"] = output
        return output
