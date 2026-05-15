from typing import Literal, TypedDict


class TextPart(TypedDict):
    type: Literal["text"]
    text: str


class ImageUrlPart(TypedDict):
    type: Literal["image_url"]
    image_url: dict[str, str]  # {"url": "data:image/jpeg;base64,..."}


MessageContent = str | list[TextPart | ImageUrlPart]


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: MessageContent
