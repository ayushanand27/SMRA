from typing import Literal

from pydantic import BaseModel, Field


class SpeechRequest(BaseModel):
    """Narrate lesson context as speech."""

    context_text: str = Field(..., min_length=20, max_length=120_000)
    output_language: Literal["english", "hindi", "roman_hindi"] = "english"
    stack: str = Field(default="openai", description="openai | opensource")
    # OpenAI-only options
    openai_voice: Literal["alloy", "echo", "fable", "onyx", "nova", "shimmer"] = "nova"
    openai_tts_model: Literal["tts-1", "tts-1-hd"] = "tts-1"
    # edge-tts: optional override (short name e.g. en-US-AriaNeural); empty = auto from language
    edge_voice: str | None = Field(default=None, max_length=80)


class SpeechResponse(BaseModel):
    audio_id: str
    filename: str
    mime_type: str
    engine: Literal["openai_tts", "edge_tts"]
    truncated: bool
    characters_used: int
    translation_applied: bool = Field(
        default=False,
        description="True when text was translated/adapted to match output_language before TTS.",
    )
