import asyncio
import logging

from openai import AsyncOpenAI

from app.core.config import Settings

logger = logging.getLogger(__name__)


async def generate_illustration_png_b64(
    settings: Settings,
    *,
    prompt: str,
    style_suffix: str,
) -> tuple[str, str]:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise ValueError(
            "OPENAI_API_KEY is missing. Add it to .env file to use DALL-E for image generation."
        )
    
    client = AsyncOpenAI(api_key=settings.openai_api_key.strip())
    full_prompt = f"{prompt.strip()}\n\nStyle: {style_suffix.strip()}"
    full_prompt = full_prompt[:4000]  # DALL-E 3 max prompt length
    
    last_error = None
    for attempt in range(1, settings.image_generation_retries + 1):
        try:
            logger.info(f"DALL-E 3 generation attempt {attempt}/{settings.image_generation_retries}")
            result = await client.images.generate(
                model="dall-e-3",
                prompt=full_prompt,
                size="1024x1024",
                quality="standard",
                n=1,
                response_format="b64_json",
            )
            if not result.data or not result.data[0].b64_json:
                raise RuntimeError("DALL-E 3 returned no image data.")
            logger.info(f"DALL-E 3 succeeded on attempt {attempt}")
            return result.data[0].b64_json, "image/png"
        except Exception as e:
            last_error = e
            logger.warning(f"DALL-E 3 attempt {attempt} failed: {e!s}")
            if attempt < settings.image_generation_retries:
                delay = settings.image_generation_retry_delay * (2 ** (attempt - 1))
                logger.info(f"Waiting {delay:.1f}s before retry...")
                await asyncio.sleep(delay)
    
    error_msg = f"Image generation failed after {settings.image_generation_retries} attempts: {last_error!s}"
    logger.error(error_msg)
    raise RuntimeError(error_msg) from last_error
