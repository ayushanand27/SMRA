from typing import Protocol, runtime_checkable

from app.services.llm.types import Message, MessageContent


@runtime_checkable
class LLMProvider(Protocol):
    """Pluggable text / vision chat completion."""

    async def complete_chat(
        self,
        messages: list[Message],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.4,
    ) -> str: ...
