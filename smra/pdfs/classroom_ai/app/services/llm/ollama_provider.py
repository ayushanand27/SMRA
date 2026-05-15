from typing import Any

import httpx

from app.core.config import Settings
from app.services.llm.types import Message, MessageContent


def _flatten_ollama_prompt(messages: list[Message], vision_model: bool) -> tuple[str, list[str] | None]:
    """Ollama vision uses a single user turn with optional base64 images (no image_url objects)."""
    system_parts: list[str] = []
    user_text_parts: list[str] = []
    images: list[str] = []

    for m in messages:
        role = m["role"]
        content: MessageContent = m["content"]
        if isinstance(content, str):
            text = content
            if role == "system":
                system_parts.append(text)
            else:
                user_text_parts.append(text)
            continue

        for part in content:
            if part["type"] == "text":
                blob = part["text"]
                if role == "system":
                    system_parts.append(blob)
                else:
                    user_text_parts.append(blob)
            elif part["type"] == "image_url":
                if not vision_model:
                    raise ValueError("Image in message but model is not configured for vision.")
                url = part["image_url"]["url"]
                if url.startswith("data:"):
                    b64 = url.split(",", 1)[1]
                    images.append(b64)
                else:
                    raise ValueError("Ollama provider expects data: URLs for images.")

    prompt = ""
    if system_parts:
        prompt += "\n\n".join(system_parts) + "\n\n"
    prompt += "\n\n".join(user_text_parts)

    if vision_model and images:
        return prompt, images
    if images:
        raise ValueError("Images provided but Ollama vision model not used for this call.")
    return prompt, None


class OllamaProvider:
    def __init__(self, settings: Settings, *, vision: bool = False) -> None:
        self._base = settings.ollama_base_url.rstrip("/")
        self._model = settings.ollama_vision_model if vision else settings.ollama_chat_model
        self._vision = vision

    async def complete_chat(
        self,
        messages: list[Message],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.4,
    ) -> str:
        prompt, images = _flatten_ollama_prompt(messages, vision_model=self._vision)
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "options": {"temperature": temperature, "num_predict": max_tokens},
            "format": "json",
        }
        if images:
            payload["messages"][0]["images"] = images

        async with httpx.AsyncClient(timeout=120.0) as client:
            r = await client.post(f"{self._base}/api/chat", json=payload)
            r.raise_for_status()
            data = r.json()

        return (data.get("message") or {}).get("content") or "{}"
