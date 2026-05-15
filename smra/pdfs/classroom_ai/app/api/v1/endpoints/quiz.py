from fastapi import APIRouter, HTTPException

from app.schemas.language import normalize_output_language
from app.schemas.quiz import QuizGenerateRequest, QuizGenerateResponse
from app.services import quiz as quiz_service

router = APIRouter()


@router.post("/generate", response_model=QuizGenerateResponse)
async def generate_quiz(body: QuizGenerateRequest) -> QuizGenerateResponse:
    stack = (body.stack or "openai").lower().strip()
    llm_provider = "openai" if stack == "openai" else "ollama"
    lang = normalize_output_language(body.output_language)

    try:
        return await quiz_service.generate_quiz(
            topic=body.topic.strip(),
            context_text=body.context_text,
            output_language=lang,
            question_count=body.question_count,
            difficulty=body.difficulty,
            llm_provider=llm_provider,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Quiz generation failed: {e!s}") from e
