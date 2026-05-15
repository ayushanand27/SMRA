from fastapi import APIRouter, HTTPException, Response
from app.schemas.audio import SpeechRequest, SpeechResponse
from app.schemas.language import normalize_output_language
from app.services import tts as tts_service

router = APIRouter()


@router.post("/speech", response_model=SpeechResponse)
async def create_speech(body: SpeechRequest) -> SpeechResponse:
    lang = normalize_output_language(body.output_language)
    stack = (body.stack or "openai").lower().strip()
    llm_provider = "openai" if stack == "openai" else "ollama"

    try:
        aid, _bytes, filename, engine, truncated, n, translation_applied = await tts_service.synthesize_speech(
            context_text=body.context_text,
            output_language=lang,
            stack=stack,
            llm_provider=llm_provider,
            openai_voice=body.openai_voice,
            openai_tts_model=body.openai_tts_model,
            edge_voice=body.edge_voice,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Speech synthesis failed: {e!s}") from e

    return SpeechResponse(
        audio_id=aid,
        filename=filename,
        mime_type="audio/mpeg",
        engine=engine,
        truncated=truncated,
        characters_used=n,
        translation_applied=translation_applied,
    )


@router.get("/{audio_id}/file")
async def download_speech(audio_id: str) -> Response:
    data = await tts_service.get_audio_file(audio_id)
    if not data:
        raise HTTPException(status_code=404, detail="Audio not found or expired.")
    blob, filename, mime = data
    return Response(
        content=blob,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
