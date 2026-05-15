import logging

from fastapi import APIRouter, HTTPException

from app.schemas.infographic import InfographicRequest, InfographicResponse
from app.schemas.language import normalize_output_language
from app.services import infographic as infographic_service

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/generate", response_model=InfographicResponse)
async def generate_infographic(body: InfographicRequest) -> InfographicResponse:
    stack = (body.stack or "openai").lower().strip()
    lang = normalize_output_language(body.output_language)
    
    logger.info(f"Infographic request: topic={body.topic[:50]}, stack={stack}, language={lang}")

    try:
        b64, mime, prompt_used = await infographic_service.generate_infographic(
            topic=body.topic.strip(),
            context_text=body.context_text,
            output_language=lang,
            stack=stack,
            style=body.style,
        )
    except ValueError as e:
        logger.warning(f"Infographic validation error: {e!s}")
        raise HTTPException(status_code=400, detail=str(e)) from e
    except RuntimeError as e:
        logger.error(f"Infographic runtime error: {e!s}")
        raise HTTPException(
            status_code=502,
            detail=f"Failed to generate infographic: {e!s}. Check that image generation service is available."
        ) from e
    except Exception as e:
        logger.error(f"Unexpected infographic error: {e!s}")
        raise HTTPException(
            status_code=502,
            detail=f"Infographic generation error: {str(e)[:200]}"
        ) from e

    return InfographicResponse(image_base64=b64, mime_type=mime, image_prompt_used=prompt_used)
