from fastapi import APIRouter, HTTPException

from app.schemas.flashcards import FlashcardsGenerateRequest, FlashcardsResponse
from app.schemas.language import normalize_output_language
from app.services import flashcards as flashcards_service

router = APIRouter()


@router.post("/generate", response_model=FlashcardsResponse)
async def generate_flashcards(body: FlashcardsGenerateRequest) -> FlashcardsResponse:
    stack = (body.stack or "openai").lower().strip()
    llm_provider = "openai" if stack == "openai" else "ollama"
    lang = normalize_output_language(body.output_language)

    try:
        return await flashcards_service.generate_flashcards(
            topic=body.topic.strip(),
            context_text=body.context_text,
            output_language=lang,
            card_count=body.card_count,
            llm_provider=llm_provider,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Flashcards generation failed: {e!s}") from e
