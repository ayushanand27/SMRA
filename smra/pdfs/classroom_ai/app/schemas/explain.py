from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class ExplainFromTextRequest(BaseModel):
    chapter_text: str = Field(..., min_length=1, description="Full or partial chapter content.")
    output_language: Literal["english", "hindi", "roman_hindi"] = Field(
        default="english",
        description="english | hindi (Devanagari) | roman_hindi (Hindi in Latin letters).",
    )
    topic_hint: str | None = Field(
        default=None,
        description="Optional focus (e.g. section title) if the text covers multiple topics.",
    )


class ExplainFromImagesRequest(BaseModel):
    """Used for JSON-only metadata when images are sent as multipart files in the endpoint."""

    output_language: Literal["english", "hindi", "roman_hindi"] = "english"
    topic_hint: str | None = None


class VisualAssetBrief(BaseModel):
    """Structured hint for the client to render or request generated media."""

    title: str
    description: str
    kind: str = Field(
        ...,
        description="e.g. diagram, analogy_illustration, timeline, graph_concept",
    )
    suggested_format: str = Field(
        default="svg_or_image",
        description="svg_or_image, mermaid, or animation_storyboard",
    )
    src: str | None = Field(
        default=None,
        description="Optional rendered image asset for the brief, usually a data URL or public image URL.",
    )
    mermaid_diagram: str | None = Field(
        default=None,
        description="Optional Mermaid source for a brief-specific diagram.",
    )


class ExplainResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    explanation_markdown: str
    simple_examples: list[str]
    visual_briefs: list[VisualAssetBrief]
    suggested_followup_topics: list[str] = Field(default_factory=list)
    video_lesson_prompt: str | None = Field(
        default=None,
        description="Single concise Sora-style prompt for a short educational animation (no copyrighted characters).",
    )
    mermaid_diagram: str | None = Field(
        default=None,
        description="Valid Mermaid source to render a diagram in the UI (flowchart/graph).",
    )
    diagram_caption: str | None = Field(
        default=None,
        description="Short legend: what the diagram shows, label meanings, or how to read it (same language as lesson).",
    )
    output_language_used: Literal["english", "hindi", "roman_hindi"] | None = Field(
        default=None,
        description="Echo of the language the server applied (verify your selection reached the API).",
    )
    pdf_extraction_notes: str | None = Field(
        default=None,
        description="When explain came from a PDF upload: short summary (pages, tables, OCR).",
    )
    source_text_used_for_context: str | None = Field(
        default=None,
        description="Raw extracted PDF text echoed for client-side quiz/slides context (same as sent to the LLM).",
    )
