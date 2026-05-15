from typing import Literal

from pydantic import BaseModel, Field


class SlideItem(BaseModel):
    title: str = Field(..., min_length=1, max_length=200)
    bullets: list[str] = Field(default_factory=list, max_length=10)
    speaker_notes: str | None = Field(default=None, max_length=4000)
    image_query: str | None = Field(
        default=None,
        description="English keywords used to find a stock photo (when PEXELS_API_KEY is set).",
    )
    photo_attribution: str | None = Field(
        default=None,
        description="Credit line for the slide image, if one was embedded.",
    )


class SlideDeckGenerateRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=200)
    context_text: str | None = Field(default=None, max_length=30000)
    output_language: Literal["english", "hindi", "roman_hindi"] = "english"
    stack: str = Field(default="openai", description="openai | opensource")
    slide_count: int = Field(default=8, ge=4, le=20)


class SlideDeckResponse(BaseModel):
    deck_id: str
    deck_title: str
    filename: str
    slides: list[SlideItem]
