"""OpenAI Sora video generation (requires API access on your OpenAI account)."""

from typing import Literal, cast

from openai import AsyncOpenAI
from app.core.config import Settings


def _video_client(settings: Settings) -> AsyncOpenAI:
    if not settings.openai_api_key or not settings.openai_api_key.strip():
        raise ValueError("OPENAI_API_KEY is required for video generation (Sora API).")
    # Chained jobs can run a long time (several segments × queue + render).
    return AsyncOpenAI(
        api_key=settings.openai_api_key.strip(),
        timeout=1200.0,
        max_retries=2,
    )


# Define VideoSeconds as a Literal type
VideoSeconds = Literal["4", "8", "12"]


def _extend_plan_for_target(total_seconds: int) -> list[VideoSeconds]:
    """
    `videos.create` is capped at 12s. Each `videos.extend` adds another 4/8/12s segment.
    There is no single API parameter for 30s — we chain segments to approximate the target.
    """
    if total_seconds <= 12:
        return []
    if total_seconds <= 24:
        return ["12"]
    if total_seconds <= 28:
        return ["12", "4"]
    if total_seconds <= 33:
        return ["12", "8"]
    return ["12", "12"]


async def create_video_job(
    settings: Settings,
    *,
    prompt: str,
    model: str,
    seconds: str,
    size: str | None,
    input_reference_image_url: str | None,
):
    client = _video_client(settings)
    kwargs: dict = {
        "prompt": prompt,
        "model": model,
        "seconds": seconds,
    }
    if size:
        kwargs["size"] = size
    if input_reference_image_url:
        kwargs["input_reference"] = {"image_url": input_reference_image_url}
    return await client.videos.create(**kwargs)


async def create_chained_video_job(
    settings: Settings,
    *,
    prompt: str,
    model: str,
    size: str | None,
    input_reference_image_url: str | None,
    chain_target_seconds: int,
):
    """
    One 12s create, then extend segments until we approximate chain_target_seconds.
    Returns the final Video metadata (last segment id is what you download).
    """
    if chain_target_seconds <= 12:
        sec = "12" if chain_target_seconds > 8 else "8" if chain_target_seconds > 4 else "4"
        return await create_video_job(
            settings,
            prompt=prompt,
            model=model,
            seconds=sec,
            size=size,
            input_reference_image_url=input_reference_image_url,
        )

    client = _video_client(settings)
    create_kwargs: dict = {
        "prompt": prompt.strip(),
        "model": model,
        "seconds": cast(VideoSeconds, "12"),
    }
    if size:
        create_kwargs["size"] = size
    if input_reference_image_url:
        create_kwargs["input_reference"] = {"image_url": input_reference_image_url}

    video = await client.videos.create_and_poll(**create_kwargs)

    if video.status == "failed":
        return video

    extend_prompt = (
        f"{prompt.strip()}\n\nContinue this same educational animation seamlessly from "
        "where the last clip ends — same style, colors, and subject, no hard cut."
    )

    for seg in _extend_plan_for_target(chain_target_seconds):
        video = await client.videos.extend(
            prompt=extend_prompt,
            seconds=cast(VideoSeconds, seg),
            video={"id": video.id},
        )
        video = await client.videos.poll(video.id)
        if video.status == "failed":
            return video

    return video


async def retrieve_video(settings: Settings, video_id: str):
    client = _video_client(settings)
    return await client.videos.retrieve(video_id)


async def download_video_bytes(settings: Settings, video_id: str) -> bytes:
    client = _video_client(settings)
    res = await client.videos.download_content(video_id, variant="video")
    return res.content
