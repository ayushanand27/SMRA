import asyncio
import base64
import hashlib
import logging

import httpx

from app.core.config import Settings

logger = logging.getLogger(__name__)


def _generate_deterministic_seed(prompt: str) -> int:
    """Generate a deterministic seed from the prompt for consistent results."""
    hash_obj = hashlib.sha256(prompt.encode())
    seed = int(hash_obj.hexdigest()[:8], 16) % (2**31 - 1)
    return seed


async def generate_illustration_png_b64(
    settings: Settings,
    *,
    prompt: str,
    style_suffix: str,
) -> tuple[str, str]:
    """Use local AUTOMATIC1111 / SD WebUI txt2img endpoint (free, open-source, local GPU).
    
    Adds retry logic and deterministic seed for consistency.
    """
    url = settings.sd_webui_url.rstrip("/") + "/sdapi/v1/txt2img"
    
    # Use deterministic seed for consistency if not explicitly set to random
    seed = settings.sd_webui_seed if settings.sd_webui_seed != -1 else _generate_deterministic_seed(prompt)
    
    payload = {
        "prompt": f"{prompt}. Style: {style_suffix}",
        "negative_prompt": "low quality, blurry, watermark, text overlay, distorted",
        "steps": 28,
        "cfg_scale": 7.5,
        "width": 1024,
        "height": 1024,
        "sampler_name": "DPM++ 2M Karras",
        "seed": seed,
    }
    
    last_error = None
    for attempt in range(1, settings.image_generation_retries + 1):
        try:
            logger.info(
                f"SD WebUI generation attempt {attempt}/{settings.image_generation_retries} "
                f"(seed: {seed})"
            )
            async with httpx.AsyncClient(timeout=180.0) as client:
                r = await client.post(url, json=payload)
                r.raise_for_status()
                data = r.json()
        except Exception as e:
            last_error = e
            logger.warning(f"SD WebUI attempt {attempt} failed: {e!s}")
            if attempt < settings.image_generation_retries:
                delay = settings.image_generation_retry_delay * (2 ** (attempt - 1))
                logger.info(f"Waiting {delay:.1f}s before retry...")
                await asyncio.sleep(delay)
            continue
        
        try:
            images = data.get("images") or []
            if not images:
                raise RuntimeError("SD WebUI returned no images.")
            
            raw = images[0]
            # Some servers may include a data URL; normalize to base64 payload only.
            if "," in raw and raw.startswith("data:"):
                raw = raw.split(",", 1)[1]
            
            # Validate base64
            base64.b64decode(raw, validate=False)
            logger.info(f"SD WebUI succeeded on attempt {attempt}")
            return raw, "image/png"
        except Exception as e:
            last_error = e
            logger.error(f"Failed to process SD WebUI response on attempt {attempt}: {e!s}")
            if attempt < settings.image_generation_retries:
                delay = settings.image_generation_retry_delay * (2 ** (attempt - 1))
                logger.info(f"Waiting {delay:.1f}s before retry...")
                await asyncio.sleep(delay)
    
    # All retries exhausted
    error_msg = (
        f"SD WebUI generation failed after {settings.image_generation_retries} attempts. "
        f"Ensure SD WebUI server is running at {settings.sd_webui_url}. "
        f"Last error: {last_error!s}"
    )
    logger.error(error_msg)
    raise ValueError(error_msg) from last_error
