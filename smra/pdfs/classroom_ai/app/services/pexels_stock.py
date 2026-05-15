"""Shared Pexels API helpers: stock photos and stock video (no generation — licensed catalog)."""

from __future__ import annotations

import re
from typing import Any

import httpx


def _sanitize_query(q: str, max_len: int = 120) -> str:
    s = re.sub(r"[^\w\s\-]", " ", q).strip()[:max_len] or "education classroom"
    return re.sub(r"\s+", " ", s)


async def fetch_landscape_photo_bytes(
    api_key: str, query: str
) -> tuple[bytes, str, str] | None:
    """Download one landscape photo; returns (bytes, mime_type, attribution) or None."""
    q = _sanitize_query(query)
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.pexels.com/v1/search",
                params={"query": q, "per_page": 1, "orientation": "landscape"},
                headers={"Authorization": api_key},
                timeout=25.0,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            photos = data.get("photos") or []
            if not photos:
                return None
            p0 = photos[0]
            src = p0.get("src") or {}
            url = src.get("large") or src.get("medium") or src.get("original")
            if not url:
                return None
            ir = await client.get(url, timeout=35.0, follow_redirects=True)
            if ir.status_code != 200:
                return None
            ct = (ir.headers.get("content-type") or "").split(";")[0].strip().lower()
            mime = ct if ct.startswith("image/") else "image/jpeg"
            photographer = str(p0.get("photographer", "Pexels"))
            pid = p0.get("id", "")
            attr = f"Photo: {photographer} / Pexels (id: {pid})"
            return ir.content, mime, attr
    except Exception:
        return None


def _pick_best_mp4_link(video_files: list[dict[str, Any]]) -> str | None:
    mp4s = [f for f in video_files if str(f.get("file_type", "")).lower() == "video/mp4" and f.get("link")]
    if not mp4s:
        return None
    quality_order = {"uhd": 0, "hd": 1, "sd": 2, "hls": 99}
    mp4s.sort(
        key=lambda f: (
            quality_order.get(str(f.get("quality", "")).lower(), 50),
            -int(f.get("width") or 0),
        )
    )
    return str(mp4s[0]["link"])


async def fetch_stock_video_mp4_bytes(api_key: str, query: str) -> tuple[bytes, str, str] | None:
    """Search Pexels videos, download best MP4; returns (bytes, attribution, quality_label) or None."""
    q = _sanitize_query(query)
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(
                "https://api.pexels.com/videos/search",
                params={"query": q, "per_page": 1, "orientation": "landscape"},
                headers={"Authorization": api_key},
                timeout=30.0,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            videos = data.get("videos") or []
            if not videos:
                return None
            v0 = videos[0]
            files = v0.get("video_files") or []
            link = _pick_best_mp4_link(files)
            if not link:
                return None
            vr = await client.get(link, timeout=120.0, follow_redirects=True)
            if vr.status_code != 200:
                return None
            user = v0.get("user") or {}
            name = str(user.get("name", "Pexels"))
            vid = v0.get("id", "")
            attr = f"Video: {name} / Pexels (id: {vid})"
            picked = next(
                (f for f in files if f.get("link") == link),
                files[0] if files else {},
            )
            qlab = str(picked.get("quality", "hd"))
            return vr.content, attr, qlab
    except Exception:
        return None
