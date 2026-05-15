import asyncio
import json
import logging
import re

from app.core.config import get_settings
from app.schemas.language import OutputLanguage, normalize_output_language
from app.services import illustration_openai, illustration_opensource
from app.services.llm.factory import get_llm_provider
from app.services.llm.types import Message

logger = logging.getLogger(__name__)


def _extract_json_obj(raw: str) -> dict | None:
    raw = raw.strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(raw[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


def _lang_note(lang: OutputLanguage) -> str:
    if lang == "english":
        return "Concept labels in the scene should be implied by icons only; image must contain NO readable text."
    if lang == "hindi":
        return "The topic is taught in Hindi; use culturally neutral school visuals, NO Devanagari text in the image."
    return "Roman Hindi context; use neutral visuals, NO letters or words in the image."


def _get_default_visual_prompt(topic: str) -> str:
    """Get a reliable default visual prompt when LLM fails."""
    return (
        f"Educational infographic poster about {topic}: clear sections, flowchart arrows, "
        f"icons for key concepts, color-coded blocks, minimal style, no text, vector design, "
        f"school-friendly, bold colors, readable layout."
    )


def _prompt_llm(*, topic: str, context_text: str | None, output_language: OutputLanguage) -> str:
    ctx = (context_text or "").strip()[:12000]
    return (
        "You write ONE concise image-generation prompt for an educational INFOGRAPHIC (diagram poster).\n"
        f"Topic: {topic}\n"
        f"{_lang_note(output_language)}\n"
        "Describe layout: clear sections, flowchart arrows, icons for key concepts, "
        "color-coded regions, simple charts, no text labels.\n"
        "Use professional educational infographic style: bold shapes, vector-like, school-friendly.\n"
        "No longer than 500 characters in the prompt field.\n"
        'Return ONLY JSON: {"visual_prompt": "<single English prompt>"}\n'
        + (f"\nLesson context to reflect:\n{ctx}\n" if ctx else "")
    )


async def _generate_visual_prompt_with_retry(
    *,
    topic: str,
    context_text: str | None,
    output_language: OutputLanguage,
    llm_provider_name: str,
) -> str:
    """Generate visual prompt from LLM with retry logic."""
    settings = get_settings()
    provider = get_llm_provider(vision=False, provider=llm_provider_name)
    
    last_error = None
    for attempt in range(1, settings.llm_prompt_generation_retries + 1):
        try:
            logger.info(f"LLM visual prompt generation attempt {attempt}/{settings.llm_prompt_generation_retries}")
            messages: list[Message] = [
                {"role": "system", "content": "You output strict JSON only. No explanations."},
                {"role": "user", "content": _prompt_llm(
                    topic=topic,
                    context_text=context_text,
                    output_language=output_language
                )},
            ]
            raw = await provider.complete_chat(messages, max_tokens=800, temperature=0.3)
            data = _extract_json_obj(raw) or {}
            vp = str(data.get("visual_prompt") or data.get("prompt") or "").strip()
            
            if len(vp) >= 20 and len(vp) <= 600:
                logger.info(f"LLM succeeded on attempt {attempt}, prompt length: {len(vp)}")
                vp = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", vp)
                return vp
            else:
                logger.warning(
                    f"LLM returned prompt with invalid length {len(vp)} on attempt {attempt}, "
                    f"expected 20-600 chars"
                )
                raise ValueError(f"Prompt too short ({len(vp)} chars)")
        except Exception as e:
            last_error = e
            logger.warning(f"LLM attempt {attempt} failed: {e!s}")
            if attempt < settings.llm_prompt_generation_retries:
                await asyncio.sleep(0.5)  # Short delay between LLM retries
    
    # Fallback to default
    default = _get_default_visual_prompt(topic)
    logger.warning(f"LLM failed after {settings.llm_prompt_generation_retries} attempts, using default prompt")
    return default


async def generate_infographic(
    *,
    topic: str,
    context_text: str | None,
    output_language: str,
    stack: str,
    style: str,
) -> tuple[str, str, str]:
    """Generate an educational infographic with stable, consistent results."""
    settings = get_settings()
    lang = normalize_output_language(output_language)
    llm_provider_name = "openai" if stack.lower().strip() == "openai" else "ollama"
    
    # Step 1: Generate visual prompt from LLM with retry logic
    logger.info(f"Starting infographic generation for topic: {topic}")
    vp = await _generate_visual_prompt_with_retry(
        topic=topic,
        context_text=context_text,
        output_language=lang,
        llm_provider_name=llm_provider_name,
    )
    
    # Step 2: Render infographic with image model
    full_prompt = (
        f"Professional educational infographic, 1024x1024, readable layout, vector design: {vp}. "
        f"Clear sections, flowchart style, school-friendly, no text labels, bold colors, crisp edges."
    )
    
    style_suffix = (style or "").strip() or (
        "flat vector infographic, bold shapes, no text, no watermark, crisp edges, school-friendly colors"
    )

    try:
        if stack.lower().strip() == "opensource":
            b64, mime = await illustration_opensource.generate_illustration_png_b64(
                settings,
                prompt=full_prompt,
                style_suffix=style_suffix,
            )
        else:
            b64, mime = await illustration_openai.generate_illustration_png_b64(
                settings,
                prompt=full_prompt,
                style_suffix=style_suffix,
            )
        logger.info("Infographic generated successfully")
    except Exception as e:
        logger.error(f"Infographic image generation failed: {e!s}")
        raise
    
    return b64, mime, full_prompt[:2000]
