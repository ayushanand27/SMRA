import os
from pathlib import Path
from typing import Optional

# Load .env relative to smra/ so scripts work no matter the CWD.
try:
    from dotenv import load_dotenv

    _SMRA_ROOT = Path(__file__).resolve().parents[1]
    _ENV_PATH = _SMRA_ROOT / ".env"
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH, override=True)
    else:
        load_dotenv(override=True)
except Exception:
    pass


def call_llm(system_prompt: str, user_prompt: str, temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> str:
    """Call the configured LLM provider and return a text response.

    Uses lazy imports so this module can be imported even if a provider SDK is missing.
    """
    provider = os.getenv("LLM_PROVIDER", "groq").lower()  # ollama | groq | gemini
    temp = 0 if temperature is None else float(temperature)
    max_t = 1000 if max_tokens is None else int(max_tokens)

    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
            from langchain_core.messages import HumanMessage, SystemMessage
        except Exception as e:
            raise RuntimeError("Install 'langchain-ollama' to use Ollama provider") from e

        llm = ChatOllama(model=os.getenv("OLLAMA_MODEL", "llama3.1"), temperature=temp)
        msgs = [SystemMessage(content=system_prompt), HumanMessage(content=user_prompt)]
        res = llm.invoke(msgs)
        # langchain_ollama returns an object with .content
        return getattr(res, "content", str(res))

    if provider == "groq":
        try:
            from groq import Groq
        except Exception as e:
            raise RuntimeError("Install the 'groq' package to use Groq provider") from e

        timeout_s = float(os.getenv("GROQ_TIMEOUT", os.getenv("LLM_TIMEOUT", "20")))
        client = Groq(api_key=os.getenv("GROQ_API_KEY"), timeout=timeout_s)
        model = os.getenv("GROQ_MODEL", "llama-3.1-8b-instant")
        r = client.chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}],
            temperature=temp,
            max_tokens=max_t,
        )
        try:
            return r.choices[0].message.content
        except Exception:
            return str(r)

    if provider == "gemini":
        try:
            import google.generativeai as genai
        except Exception as e:
            raise RuntimeError("Install 'google-generativeai' to use Gemini provider") from e
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        model = genai.GenerativeModel(model_name)
        return model.generate_content(f"{system_prompt}\n\n{user_prompt}").text

    raise ValueError(f"Unsupported LLM_PROVIDER: {provider}")
