from typing import Literal

from pydantic import BaseModel, Field


class IllustrationRequest(BaseModel):
    prompt: str = Field(..., min_length=4, max_length=3900)
    stack: str = Field(default="openai", description="openai | opensource")
    source: Literal["ai", "pexels"] = Field(
        default="ai",
        description="ai = DALL·E or SD WebUI; pexels = stock photo from Pexels (requires PEXELS_API_KEY).",
    )
    style: str = Field(
        default=(
            "Photorealistic or clean textbook-style educational scene, natural lighting, "
            "accurate proportions; include clear labeled parts or a simple legend in the scene if it is a diagram; "
            "no watermarks; minimal readable labels only if essential; avoid cluttered text."
        ),
        description="Appended to the model prompt for safety and look.",
    )


class IllustrationResponse(BaseModel):
    image_base64: str
    mime_type: str = "image/png"
