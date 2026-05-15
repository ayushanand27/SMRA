from openai import AsyncOpenAI

from app.core.config import Settings
from app.services.llm.types import Message


class OpenAIProvider:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required when LLM_PROVIDER=openai")
        self._client = AsyncOpenAI(api_key=settings.openai_api_key)
        self._model = settings.openai_chat_model

    async def complete_chat(
        self,
        messages: list[Message],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.4,
    ) -> str:
        # OpenAI SDK accepts typed dict-like message shapes for vision.
        normalized: list[dict] = []
        for m in messages:
            normalized.append(dict(m))  # type: ignore[arg-type]

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=normalized,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            temperature=temperature,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content
        if content is None:
            return "{}"
        return content.strip()
