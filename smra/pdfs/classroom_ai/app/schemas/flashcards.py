from typing import Literal

from pydantic import BaseModel, Field


class FlashcardItem(BaseModel):
    front: str = Field(..., min_length=1, max_length=500)
    back: str = Field(..., min_length=1, max_length=2000)


class FlashcardsGenerateRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=200)
    context_text: str | None = Field(default=None, max_length=30000)
    output_language: Literal["english", "hindi", "roman_hindi"] = "english"
    stack: str = Field(default="openai", description="openai | opensource")
    card_count: int = Field(default=12, ge=4, le=40)


class FlashcardsResponse(BaseModel):
    topic: str
    output_language_used: Literal["english", "hindi", "roman_hindi"]
    cards: list[FlashcardItem]
