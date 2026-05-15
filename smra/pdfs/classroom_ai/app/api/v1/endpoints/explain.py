from typing import Annotated, Literal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from app.schemas.explain import ExplainFromTextRequest, ExplainResponse
from app.schemas.language import normalize_output_language
from app.services import explanation as explanation_service

router = APIRouter()

ModelStack = Literal["openai", "opensource"]


def _to_llm_provider(stack: ModelStack) -> Literal["openai", "ollama"]:
    return "openai" if stack == "openai" else "ollama"


# Annotated + File() helps OpenAPI/Swagger show multipart controls for file lists.
ChapterScreenshots = Annotated[
    list[UploadFile],
    File(description="One or more PNG/JPEG screenshots of the chapter"),
]


@router.post("/text", response_model=ExplainResponse)
async def explain_text(
    body: ExplainFromTextRequest,
    stack: ModelStack = "openai",
) -> ExplainResponse:
    """JSON body. Multi-line `chapter_text` must use `\\n` in JSON, not raw newlines."""
    try:
        return await explanation_service.explain_from_text(
            body.chapter_text,
            output_language=body.output_language,
            topic_hint=body.topic_hint,
            llm_provider=_to_llm_provider(stack),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM request failed: {e!s}") from e


@router.post("/text-form", response_model=ExplainResponse)
async def explain_text_form(
    chapter_text: Annotated[str, Form(..., description="Full chapter; newlines allowed.")],
    output_language: Annotated[str, Form()] = "english",
    topic_hint: Annotated[str | None, Form()] = None,
    stack: Annotated[ModelStack, Form()] = "openai",
) -> ExplainResponse:
    hint = (topic_hint or "").strip() or None
    lang = normalize_output_language(output_language)
    try:
        return await explanation_service.explain_from_text(
            chapter_text,
            output_language=lang,
            topic_hint=hint,
            llm_provider=_to_llm_provider(stack),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM request failed: {e!s}") from e


@router.post("/image", response_model=ExplainResponse)
async def explain_one_image(
    file: Annotated[UploadFile, File(description="One PNG/JPEG screenshot of the chapter")],
    output_language: str = Form("english"),
    topic_hint: str | None = Form(None),
    stack: ModelStack = Form("openai"),
) -> ExplainResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="Uploaded file must have a filename.")
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")

    lang = normalize_output_language(output_language)
    try:
        return await explanation_service.explain_from_image_bytes(
            [(file.filename, data)],
            output_language=lang,
            topic_hint=topic_hint or None,
            llm_provider=_to_llm_provider(stack),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM request failed: {e!s}") from e


@router.post("/images", response_model=ExplainResponse)
async def explain_images(
    files: ChapterScreenshots,
    output_language: str = Form("english"),
    topic_hint: str | None = Form(None),
    stack: ModelStack = Form("openai"),
) -> ExplainResponse:
    if not files:
        raise HTTPException(status_code=400, detail="At least one image file is required.")

    pairs: list[tuple[str, bytes]] = []
    for uf in files:
        if not uf.filename:
            continue
        data = await uf.read()
        if data:
            pairs.append((uf.filename, data))

    if not pairs:
        raise HTTPException(status_code=400, detail="No readable image bytes in upload.")

    lang = normalize_output_language(output_language)
    try:
        return await explanation_service.explain_from_image_bytes(
            pairs,
            output_language=lang,
            topic_hint=topic_hint or None,
            llm_provider=_to_llm_provider(stack),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"LLM request failed: {e!s}") from e


def _form_bool(raw: str) -> bool:
    return str(raw).lower() in ("true", "1", "yes", "on")


@router.post("/pdf", response_model=ExplainResponse)
async def explain_pdf(
    file: Annotated[UploadFile, File(description="PDF chapter or textbook excerpt")],
    output_language: str = Form("english"),
    topic_hint: str | None = Form(None),
    stack: ModelStack = Form("openai"),
    ocr_pages: str = Form("true"),
    ocr_images: str = Form("true"),
) -> ExplainResponse:
    """Extract text page-by-page (tables + optional OCR), then explain using that context."""
    if not file.filename or not str(file.filename).lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Upload a single .pdf file.")
    data = await file.read()
    if not data or len(data) > 40 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF is empty or too large (max 40 MB).")

    lang = normalize_output_language(output_language)
    try:
        return await explanation_service.explain_from_pdf_bytes(
            data,
            output_language=lang,
            topic_hint=(topic_hint or "").strip() or None,
            llm_provider=_to_llm_provider(stack),
            ocr_pages=_form_bool(ocr_pages),
            ocr_images=_form_bool(ocr_images),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"PDF explain failed: {e!s}") from e
