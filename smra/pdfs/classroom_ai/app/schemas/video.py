from typing import Literal

from pydantic import BaseModel, Field


class VideoJobCreateRequest(BaseModel):
    prompt: str = Field(..., min_length=1, max_length=32000)
    stack: str = Field(
        default="openai",
        description=(
            "openai | opensource | pexels | lesson_overview "
            "(narrated explainer MP4 from source text; Notebook LM–style)"
        ),
    )
    seconds: Literal["4", "8", "12"] = "4"
    model: str = Field(default="sora-2", description="e.g. sora-2, sora-2-pro")
    size: str | None = Field(
        default=None,
        description="720x1280, 1280x720, 1024x1792, 1792x1024; omit for API default",
    )
    input_reference_image_url: str | None = Field(
        default=None,
        description="Optional data URL or HTTPS URL to guide visuals (first textbook page).",
    )
    chain_target_seconds: int | None = Field(
        default=None,
        ge=12,
        le=48,
        description=(
            "When >= 18, runs create(12s) + extend segments to approximate this total. "
            "Example: 30 → ~32s (12+12+8). OpenAI does not offer one native 30s clip. "
            "Values 12–17 are ignored for chaining; use `seconds` for a single 4/8/12s clip."
        ),
    )
    opensource_animation: Literal["classic", "motion_plus"] | None = Field(
        default=None,
        description=(
            "Open-source local MP4 only: classic = lightweight gradient + sketch; "
            "motion_plus = higher fps, Ken Burns-style framing, smoother line transitions."
        ),
    )
    lesson_source_text: str | None = Field(
        default=None,
        max_length=32000,
        description="For stack=lesson_overview: full chapter / lesson text to narrate (ground truth for the script).",
    )
    lesson_overview_style: Literal["explainer", "brief"] = Field(
        default="explainer",
        description="explainer ≈ more segments; brief = shorter overview.",
    )
    output_language: Literal["english", "hindi", "roman_hindi"] = Field(
        default="english",
        description="Spoken + on-screen language for lesson_overview.",
    )
    lesson_use_pexels_background: bool = Field(
        default=False,
        description="If true and PEXELS_API_KEY is set, each segment uses a stock photo under text.",
    )
    lesson_llm_stack: Literal["openai", "opensource"] = Field(
        default="opensource",
        description="Which stack runs script generation + TTS for lesson_overview (matches app Model stack).",
    )


class VideoErrorPublic(BaseModel):
    code: str | None = None
    message: str | None = None


class VideoJobPublic(BaseModel):
    id: str
    status: str
    progress: float | None = None
    model: str | None = None
    seconds: str | None = None
    size: str | None = None
    error: VideoErrorPublic | None = None
