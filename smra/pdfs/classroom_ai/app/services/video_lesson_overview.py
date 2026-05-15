"""
Narrated multi-segment 'lesson overview' MP4 (Notebook LM–style explainer).

Pipeline: LLM → script JSON → per-segment slide image + TTS → ffmpeg mux + concat.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import subprocess
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont
from pydantic import BaseModel, Field, ValidationError

from app.core.config import Settings
from app.schemas.language import OutputLanguage
from app.services.llm.factory import get_llm_provider
from app.services.llm.types import Message
from app.services.pexels_stock import fetch_landscape_photo_bytes
from app.services import tts as tts_service


class OverviewSegment(BaseModel):
    heading: str = Field(..., min_length=2, max_length=200)
    narration: str = Field(..., min_length=10, max_length=3500)
    visual_hint: str = Field(default="", max_length=200)


class OverviewScript(BaseModel):
    title: str = Field(default="Lesson overview", max_length=200)
    segments: list[OverviewSegment] = Field(min_length=1, max_length=12)


@dataclass
class LessonOverviewJob:
    id: str
    status: Literal["queued", "in_progress", "completed", "failed"] = "queued"
    progress: float = 0.0
    model: str = "lesson-overview-explainer"
    seconds: str | None = None
    size: str | None = "1280x720"
    error: dict | None = None
    bytes_data: bytes | None = None


_jobs: dict[str, LessonOverviewJob] = {}
_lock = asyncio.Lock()


def _extract_json_obj(raw: str) -> dict | None:
    raw = raw.strip()
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(raw[start : end + 1])
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


def _lang_name(lang: OutputLanguage) -> str:
    if lang == "english":
        return "English"
    if lang == "hindi":
        return "Hindi (Devanagari script)"
    return "Roman Hindi (Latin letters only)"


def _script_prompt(
    source: str,
    *,
    style: Literal["explainer", "brief"],
    output_language: OutputLanguage,
    n_segments: int,
) -> str:
    return (
        "You are an expert instructional designer. Create a narrated video overview script in the style of "
        "an educational explainer (clear, structured, faithful to the source).\n\n"
        f"OUTPUT LANGUAGE for every `heading` and `narration` field: {_lang_name(output_language)}.\n"
        f"Target segment count: exactly {n_segments} segments.\n"
        f"Style: {'full explainer — connect ideas across segments' if style == 'explainer' else 'brief — shorter narration per segment'}.\n\n"
        "SOURCE MATERIAL (only use facts from here; do not invent citations or details not implied by the text):\n"
        "---\n"
        f"{source[:28000]}\n"
        "---\n\n"
        "Return JSON only (no markdown) with this shape:\n"
        '{"title": string, "segments": ['
        '{"heading": string, "narration": string, "visual_hint": string}'
        "]}\n"
        "Rules:\n"
        "- Each narration should be 70–180 words (shorter if the source is short), natural spoken English/Hindi as selected.\n"
        "- `heading` is a short on-screen chapter title (max ~8 words).\n"
        "- `visual_hint` is 3–8 English keywords for a stock/educational background image (not a sentence).\n"
        "- Segments must not repeat; build a coherent arc (intro → core ideas → takeaway).\n"
    )


async def _generate_script(
    settings: Settings,
    *,
    source: str,
    style: Literal["explainer", "brief"],
    output_language: OutputLanguage,
    stack: str,
) -> OverviewScript:
    n_segments = 6 if style == "explainer" else 4
    provider = get_llm_provider(vision=False, settings=settings, provider="openai" if stack == "openai" else "ollama")
    messages: list[Message] = [
        {"role": "system", "content": "You output strict JSON only for lesson overview scripts."},
        {
            "role": "user",
            "content": _script_prompt(source, style=style, output_language=output_language, n_segments=n_segments),
        },
    ]
    raw = await provider.complete_chat(messages, max_tokens=8000, temperature=0.35)
    data = _extract_json_obj(raw) or {}
    try:
        return OverviewScript.model_validate(
            {
                "title": data.get("title") or "Lesson overview",
                "segments": data.get("segments") or [],
            }
        )
    except ValidationError:
        pass
    return _fallback_script_from_text(source, n_segments=n_segments)


def _fallback_script_from_text(source: str, *, n_segments: int) -> OverviewScript:
    """Split source into crude segments if the LLM fails."""
    parts = [p.strip() for p in re.split(r"\n\n+", source) if len(p.strip()) > 40]
    if len(parts) < n_segments:
        chunk = max(200, len(source) // max(n_segments, 1))
        parts = [source[i : i + chunk].strip() for i in range(0, len(source), chunk) if source[i : i + chunk].strip()]
    parts = parts[:n_segments]
    segs: list[OverviewSegment] = []
    for i, p in enumerate(parts):
        segs.append(
            OverviewSegment(
                heading=f"Part {i + 1}",
                narration=p[:1200],
                visual_hint="education learning classroom",
            )
        )
    while len(segs) < n_segments and len(segs) < 4:
        segs.append(
            OverviewSegment(
                heading=f"Review {len(segs) + 1}",
                narration=source[:800],
                visual_hint="study notes",
            )
        )
    return OverviewScript(title="Lesson overview", segments=segs[: max(3, min(n_segments, len(segs)))])


def _load_fonts() -> tuple[ImageFont.FreeTypeFont | ImageFont.ImageFont, ImageFont.FreeTypeFont | ImageFont.ImageFont]:
    for path, title_sz, body_sz in (
        ("/System/Library/Fonts/Supplemental/Arial Unicode.ttf", 44, 26),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 44, 26),
        ("C:\\Windows\\Fonts\\arial.ttf", 44, 26),
    ):
        try:
            return ImageFont.truetype(path, title_sz), ImageFont.truetype(path, body_sz)
        except OSError:
            continue
    f = ImageFont.load_default()
    return f, f


def _wrap_lines(text: str, font: ImageFont.ImageFont, draw: ImageDraw.ImageDraw, max_width: int) -> list[str]:
    words = text.replace("\n", " ").split()
    lines: list[str] = []
    cur = ""
    for w in words:
        trial = (cur + " " + w).strip()
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:14]


def _render_slide(
    heading: str,
    narration: str,
    *,
    bg_bytes: bytes | None,
    width: int = 1280,
    height: int = 720,
) -> bytes:
    title_font, body_font = _load_fonts()
    if bg_bytes:
        try:
            import io

            bg = Image.open(io.BytesIO(bg_bytes)).convert("RGB")
            bg = bg.resize((width, height), Image.Resampling.LANCZOS)
            overlay = Image.new("RGBA", (width, height), (15, 18, 35, 210))
            bg_rgba = bg.convert("RGBA")
            composed = Image.alpha_composite(bg_rgba, overlay)
            img = composed.convert("RGB")
        except Exception:
            img = Image.new("RGB", (width, height), (22, 26, 48))
    else:
        img = Image.new("RGB", (width, height), (22, 26, 48))
        draw_g = ImageDraw.Draw(img)
        for y in range(height):
            t = y / max(height - 1, 1)
            r = int(22 + (35 - 22) * t)
            g = int(26 + (40 - 26) * t)
            b = int(48 + (72 - 48) * t)
            draw_g.line([(0, y), (width, y)], fill=(r, g, b))

    draw = ImageDraw.Draw(img)
    pad = 56
    max_w = width - 2 * pad
    title_lines = _wrap_lines(heading[:180], title_font, draw, max_w)
    y = 48
    for ln in title_lines[:2]:
        draw.text((pad, y), ln, fill=(255, 255, 255), font=title_font)
        y += 52

    body = narration[:900]
    body_lines = _wrap_lines(body, body_font, draw, max_w)
    y = 160
    for ln in body_lines:
        draw.text((pad, y), ln, fill=(230, 235, 245), font=body_font)
        y += 34
        if y > height - 80:
            break

    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _ffprobe_path(ffmpeg_bin: str) -> str:
    p = Path(ffmpeg_bin)
    cand = p.parent / ("ffprobe.exe" if p.suffix.lower() == ".exe" else "ffprobe")
    if cand.is_file():
        return str(cand)
    return "ffprobe"


def _ffprobe_duration(ffmpeg_bin: str, media_path: Path) -> float:
    probe = _ffprobe_path(ffmpeg_bin)
    try:
        r = subprocess.run(
            [
                probe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(media_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60,
        )
        return float(r.stdout.strip())
    except Exception:
        return 30.0


def _mux_still_plus_audio(ffmpeg_bin: str, image_png: Path, audio_mp3: Path, out_mp4: Path) -> None:
    subprocess.run(
        [
            ffmpeg_bin,
            "-y",
            "-loop",
            "1",
            "-i",
            str(image_png),
            "-i",
            str(audio_mp3),
            "-c:v",
            "libx264",
            "-tune",
            "stillimage",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-shortest",
            "-movflags",
            "+faststart",
            str(out_mp4),
        ],
        capture_output=True,
        check=True,
        timeout=600,
    )


def _concat_mp4s(ffmpeg_bin: str, parts: list[Path], out: Path) -> None:
    if len(parts) == 1:
        out.write_bytes(parts[0].read_bytes())
        return
    lst = out.parent / f"concat_{uuid.uuid4().hex[:8]}.txt"
    try:
        lines = []
        for p in parts:
            s = str(p.resolve()).replace("'", "'\\''")
            lines.append(f"file '{s}'")
        lst.write_text("\n".join(lines), encoding="utf-8")
        subprocess.run(
            [ffmpeg_bin, "-y", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(out)],
            capture_output=True,
            check=True,
            timeout=600,
        )
    finally:
        lst.unlink(missing_ok=True)


async def create_job(
    settings: Settings,
    *,
    source_text: str,
    stack: str,
    style: Literal["explainer", "brief"],
    output_language: OutputLanguage,
    use_pexels_background: bool,
) -> LessonOverviewJob:
    jid = f"lovid_{uuid.uuid4().hex[:12]}"
    job = LessonOverviewJob(id=jid)
    async with _lock:
        _jobs[jid] = job
    asyncio.create_task(
        _run_job(
            job,
            settings=settings,
            source_text=source_text.strip(),
            stack=stack,
            style=style,
            output_language=output_language,
            use_pexels_background=use_pexels_background,
        )
    )
    return job


async def _run_job(
    job: LessonOverviewJob,
    *,
    settings: Settings,
    source_text: str,
    stack: str,
    style: Literal["explainer", "brief"],
    output_language: OutputLanguage,
    use_pexels_background: bool,
) -> None:
    tmpdir = Path(tempfile.mkdtemp(prefix="lov_"))
    ffmpeg_bin = imageio_ffmpeg.get_ffmpeg_exe()
    pexels_key = (settings.pexels_api_key or "").strip() if use_pexels_background else ""

    try:
        job.status = "in_progress"
        job.progress = 0.05
        script = await _generate_script(settings, source=source_text, style=style, output_language=output_language, stack=stack)
        job.progress = 0.12

        n = len(script.segments)
        parts: list[Path] = []
        total_dur = 0.0

        for i, seg in enumerate(script.segments):
            bg: bytes | None = None
            if pexels_key:
                q = (seg.visual_hint or "education learning")[:120]
                out = await fetch_landscape_photo_bytes(pexels_key, q)
                if out:
                    bg = out[0]

            png_bytes = _render_slide(seg.heading, seg.narration, bg_bytes=bg)
            img_path = tmpdir / f"seg_{i}.png"
            img_path.write_bytes(png_bytes)

            mp3_bytes = await tts_service.synthesize_segment_mp3(
                seg.narration,
                stack=stack,
                output_language=output_language,
            )
            mp3_path = tmpdir / f"seg_{i}.mp3"
            mp3_path.write_bytes(mp3_bytes)

            seg_mp4 = tmpdir / f"seg_{i}.mp4"
            _mux_still_plus_audio(ffmpeg_bin, img_path, mp3_path, seg_mp4)
            parts.append(seg_mp4)
            total_dur += _ffprobe_duration(ffmpeg_bin, seg_mp4)
            job.progress = 0.12 + 0.78 * ((i + 1) / max(n, 1))

        final = tmpdir / "overview.mp4"
        _concat_mp4s(ffmpeg_bin, parts, final)
        job.bytes_data = final.read_bytes()
        job.seconds = str(int(math.ceil(total_dur))) if total_dur else None
        job.progress = 1.0
        job.status = "completed"
    except Exception as e:  # noqa: BLE001
        job.status = "failed"
        job.error = {"code": "lesson_overview_failed", "message": str(e)}
    finally:
        import shutil

        shutil.rmtree(tmpdir, ignore_errors=True)


async def get_job(video_id: str) -> LessonOverviewJob:
    async with _lock:
        if video_id not in _jobs:
            raise ValueError(f"Unknown lesson overview id: {video_id}")
        return _jobs[video_id]


async def get_video_bytes(video_id: str) -> bytes:
    job = await get_job(video_id)
    if job.status != "completed" or not job.bytes_data:
        raise ValueError("Video not ready")
    return job.bytes_data
