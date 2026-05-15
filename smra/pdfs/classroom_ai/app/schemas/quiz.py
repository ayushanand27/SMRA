from typing import Literal

from pydantic import BaseModel, Field


class QuizGenerateRequest(BaseModel):
    topic: str = Field(..., min_length=2, max_length=200)
    context_text: str | None = Field(default=None, max_length=30000)
    output_language: Literal["english", "hindi", "roman_hindi"] = "english"
    stack: str = Field(default="openai", description="openai | opensource")
    question_count: int = Field(default=5, ge=1, le=15)
    difficulty: Literal["remedial", "standard", "advanced"] = "standard"


class QuizQuestion(BaseModel):
    id: str
    question: str
    options: list[str] = Field(min_length=2, max_length=6)
    correct_option_index: int
    correct_explanation: str
    wrong_explanation: str
    option_explanations: list[str] | None = None


class QuizGenerateResponse(BaseModel):
    topic: str
    output_language_used: Literal["english", "hindi", "roman_hindi"]
    questions: list[QuizQuestion]
