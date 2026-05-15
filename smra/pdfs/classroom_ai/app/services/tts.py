import asyncio
import re
import uuid
from typing import Literal

import httpx
from openai import AsyncOpenAI

from app.core.config import Settings, get_settings
from app.schemas.language import OutputLanguage

_lock = asyncio.Lock()
_audio_store: dict[str, tuple[bytes, str, str]] = {}
# id -> (bytes, filename, mime_type)

_MAX_OPENAI = 4000
_MAX_EDGE = 50_000
_MAX_TRANSLATE_IN = 12_000


def _strip_for_speech(raw: str) -> str:
    s = re.sub(r"```[\s\S]*?```", " ", raw)
    s = re.sub(r"`([^`]+)`", r"\1", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    s = re.sub(r"[#*_>|]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _clean_plain_llm_output(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^```[a-zA-Z]*\s*", "", s)
    s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def _devanagari_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha() or ("\u0900" <= c <= "\u097f")]
    if not letters:
        return 0.0
    dev = sum(1 for c in letters if "\u0900" <= c <= "\u097f")
    return dev / len(letters)


def _latin_letter_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    lat = sum(1 for c in letters if "a" <= c.lower() <= "z")
    return lat / len(letters)


async def _ollama_plain_chat(settings: Settings, user_content: str, *, num_predict: int = 8000) -> str:
    """Ollama chat without JSON schema — required for reliable Devanagari / long translations."""
    url = f"{settings.ollama_base_url.rstrip('/')}/api/chat"
    payload: dict = {
        "model": settings.ollama_chat_model,
        "messages": [{"role": "user", "content": user_content}],
        "stream": False,
        "options": {"temperature": 0.15, "num_predict": num_predict},
    }
    async with httpx.AsyncClient(timeout=180.0) as client:
        r = await client.post(url, json=payload)
        r.raise_for_status()
        data = r.json()
    return ((data.get("message") or {}).get("content") or "").strip()


async def _openai_plain_chat(settings: Settings, user_content: str, *, max_tokens: int = 6000) -> str:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise ValueError("OPENAI_API_KEY is required for translation when using the OpenAI stack.")
    client = AsyncOpenAI(api_key=settings.openai_api_key.strip())
    resp = await client.chat.completions.create(
        model=settings.openai_chat_model,
        messages=[{"role": "user", "content": user_content}],
        max_tokens=max_tokens,
        temperature=0.15,
    )
    ch = resp.choices[0].message.content
    return (ch or "").strip()


async def _translate_for_speech_plain(
    text: str,
    output_language: OutputLanguage,
    llm_provider: str,
) -> tuple[str, bool]:
    """Translate lesson text into the output language using plain LLM output (not JSON)."""
    if output_language == "english":
        return text, False

    excerpt = text[:_MAX_TRANSLATE_IN].strip()
    settings = get_settings()

    if output_language == "hindi":
        if _devanagari_ratio(excerpt) >= 0.45:
            return excerpt, False

        def _hindi_prompt(strict: bool) -> str:
            extra = ""
            if strict:
                extra = (
                    "\nIMPORTANT: Your previous answer may have been wrong. "
                    "This time output ONLY Devanagari script (Hindi). "
                    "Do not write English sentences.\n"
                )
            return (
                f"{extra}"
                "You are a Hindi school teacher. Translate the lesson passage below into Hindi for audio narration.\n"
                "Rules:\n"
                "- Use Devanagari script ONLY for all Hindi words.\n"
                "- Keep technical terms: use Hindi textbook style or transliterate to Devanagari.\n"
                "- Output ONLY the translated passage. No title, no 'Here is', no JSON, no quotes around the whole text.\n\n"
                "LESSON TEXT:\n"
                f"{excerpt}"
            )

        raw = ""
        for strict in (False, True):
            if llm_provider == "openai":
                raw = await _openai_plain_chat(settings, _hindi_prompt(strict), max_tokens=6000)
            else:
                raw = await _ollama_plain_chat(settings, _hindi_prompt(strict), num_predict=8000)
            raw = _clean_plain_llm_output(raw)
            if len(raw) < 30:
                continue
            dr = _devanagari_ratio(raw)
            if dr >= 0.06:
                return raw, True
            if strict and dr >= 0.02:
                return raw, True
        if len(raw) >= 30:
            return raw, True
        return text, False

    # roman_hindi
    if _latin_letter_ratio(excerpt) >= 0.85 and _devanagari_ratio(excerpt) < 0.03:
        return excerpt, False

    user_prompt = (
        "You are a Hindi teacher. Rewrite the lesson below as Roman Hindi only "
        "(Hindi in Latin letters A–Z; common words like 'hai', 'ke', 'mein'; NO Devanagari script).\n"
        "Output ONLY the passage. No JSON, no preamble.\n\n"
        f"LESSON TEXT:\n{excerpt}"
    )
    if llm_provider == "openai":
        raw = await _openai_plain_chat(settings, user_prompt, max_tokens=6000)
    else:
        raw = await _ollama_plain_chat(settings, user_prompt, num_predict=8000)
    raw = _clean_plain_llm_output(raw)
    if len(raw) >= 40:
        return raw, True
    return text, False


def _edge_voice_for_language(lang: OutputLanguage, override: str | None) -> str:
    if override and override.strip():
        return override.strip()
    if lang == "english":
        return "en-US-AriaNeural"
    if lang == "hindi":
        return "hi-IN-SwaraNeural"
    return "en-IN-PrabhatNeural"


async def _openai_speech(
    text: str,
    *,
    voice: str,
    model: str,
) -> bytes:
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is required for OpenAI text-to-speech.")
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    response = await client.audio.speech.create(
        model=model,
        voice=voice,  # type: ignore[arg-type]
        input=text,
        response_format="mp3",
    )
    data = getattr(response, "content", None)
    if isinstance(data, (bytes, bytearray)):
        return bytes(data)
    read_fn = getattr(response, "read", None)
    if callable(read_fn):
        out = read_fn()
        if isinstance(out, (bytes, bytearray)):
            return bytes(out)
    raise RuntimeError("Unexpected OpenAI speech response shape.")


async def _edge_speech(text: str, voice: str) -> bytes:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice)
    chunks: list[bytes] = []
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            chunks.append(chunk["data"])
    return b"".join(chunks)


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    return text[: limit - 1].rsplit(" ", 1)[0] + "…", True


async def synthesize_speech(
    *,
    context_text: str,
    output_language: OutputLanguage,
    stack: str,
    llm_provider: str,
    openai_voice: str,
    openai_tts_model: str,
    edge_voice: str | None,
) -> tuple[str, bytes, str, Literal["openai_tts", "edge_tts"], bool, int, bool]:
    cleaned = _strip_for_speech(context_text)
    if len(cleaned) < 20:
        raise ValueError("Context is too short to narrate after cleaning.")

    speech_text, translation_applied = await _translate_for_speech_plain(
        cleaned,
        output_language,
        llm_provider=llm_provider,
    )

    use_openai = stack.lower().strip() == "openai"

    if use_openai:
        text, truncated = _truncate(speech_text, _MAX_OPENAI)
        audio = await _openai_speech(
            text,
            voice=openai_voice,
            model=openai_tts_model,
        )
        engine: Literal["openai_tts", "edge_tts"] = "openai_tts"
        mime = "audio/mpeg"
    else:
        text, truncated = _truncate(speech_text, _MAX_EDGE)
        v = _edge_voice_for_language(output_language, edge_voice)
        audio = await _edge_speech(text, v)
        engine = "edge_tts"
        mime = "audio/mpeg"

    aid = f"aud_{uuid.uuid4().hex[:16]}"
    safe = re.sub(r'[<>:"/\\|?*]+', "", output_language)[:20] or "lesson"
    filename = f"classroom-lesson-{safe}.mp3"

    async with _lock:
        _audio_store[aid] = (audio, filename, mime)

    return aid, audio, filename, engine, truncated, len(text), translation_applied


async def get_audio_file(audio_id: str) -> tuple[bytes, str, str] | None:
    async with _lock:
        return _audio_store.get(audio_id)


async def synthesize_segment_mp3(
    text: str,
    *,
    stack: str,
    output_language: OutputLanguage,
    openai_voice: str = "nova",
    openai_tts_model: str = "tts-1",
    edge_voice: str | None = None,
) -> bytes:
    """Short narration for one video segment (no audio store id). Expect text already in target language."""
    cleaned = _strip_for_speech(text)
    if len(cleaned) < 4:
        cleaned = text.strip()[:4000]
    use_openai = stack.lower().strip() == "openai"
    if use_openai:
        chunk, _ = _truncate(cleaned, _MAX_OPENAI)
        return await _openai_speech(chunk, voice=openai_voice, model=openai_tts_model)
    chunk, _ = _truncate(cleaned, _MAX_EDGE)
    v = _edge_voice_for_language(output_language, edge_voice)
    return await _edge_speech(chunk, v)
