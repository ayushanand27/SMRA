"""Pexels stock video: search catalog and download MP4 (not AI-generated)."""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from typing import Literal

from app.core.config import Settings
from app.services.pexels_stock import fetch_stock_video_mp4_bytes


@dataclass
class PexelsVideoJob:
    id: str
    status: Literal["queued", "in_progress", "completed", "failed"] = "queued"
    progress: float = 0.0
    model: str = "pexels-stock-video"
    seconds: str | None = None
    size: str | None = None
    error: dict | None = None
    bytes_data: bytes | None = None


_jobs: dict[str, PexelsVideoJob] = {}
_lock = asyncio.Lock()


async def create_job(settings: Settings, prompt: str) -> PexelsVideoJob:
    key = (settings.pexels_api_key or "").strip()
    if not key:
        raise ValueError("PEXELS_API_KEY is required for Pexels stock video. Add it to your .env file.")

    jid = f"pexelsvid_{uuid.uuid4().hex[:12]}"
    job = PexelsVideoJob(id=jid)
    async with _lock:
        _jobs[jid] = job

    asyncio.create_task(_run_job(job, key, prompt.strip()))
    return job


async def _run_job(job: PexelsVideoJob, api_key: str, prompt: str) -> None:
    try:
        job.status = "in_progress"
        job.progress = 0.2
        out = await fetch_stock_video_mp4_bytes(api_key, prompt)
        job.progress = 0.85
        if not out:
            job.status = "failed"
            job.error = {
                "code": "pexels_no_video",
                "message": "No matching stock video found for this prompt. Try shorter keywords (e.g. photosynthesis, classroom).",
            }
            return
        data, _attr, _qlab = out
        job.bytes_data = data
        job.seconds = None
        job.size = None
        job.progress = 1.0
        job.status = "completed"
    except Exception as e:  # noqa: BLE001
        job.status = "failed"
        job.error = {"code": "pexels_video_failed", "message": str(e)}


async def get_job(video_id: str) -> PexelsVideoJob:
    async with _lock:
        if video_id not in _jobs:
            raise ValueError(f"Unknown Pexels video id: {video_id}")
        return _jobs[video_id]


async def get_video_bytes(video_id: str) -> bytes:
    job = await get_job(video_id)
    if job.status != "completed" or not job.bytes_data:
        raise ValueError("Video not ready")
    return job.bytes_data
