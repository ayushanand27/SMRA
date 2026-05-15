import asyncio
import math
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import imageio.v2 as imageio
import numpy as np
from PIL import Image, ImageDraw, ImageFont


@dataclass
class LocalVideoJob:
    id: str
    status: Literal["queued", "in_progress", "completed", "failed"] = "queued"
    progress: float = 0.0
    model: str = "opensource-local-animation"
    seconds: str | None = None
    size: str | None = "1280x720"
    error: dict | None = None
    bytes_data: bytes | None = None


def _model_label(preset: Literal["classic", "motion_plus"]) -> str:
    return (
        "opensource-local-motion-plus"
        if preset == "motion_plus"
        else "opensource-local-animation"
    )


def _load_font_pair() -> tuple[ImageFont.ImageFont, ImageFont.ImageFont]:
    for path in (
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "C:\\Windows\\Fonts\\arial.ttf",
    ):
        try:
            return ImageFont.truetype(path, 40), ImageFont.truetype(path, 22)
        except OSError:
            continue
    f = ImageFont.load_default()
    return f, f


_jobs: dict[str, LocalVideoJob] = {}
_lock = asyncio.Lock()


def _split_lines(prompt: str) -> list[str]:
    bits = [b.strip() for b in prompt.replace("\n", ". ").split(".") if b.strip()]
    return bits[:8] or [prompt.strip()[:120] or "Learning animation"]


def _detect_sketch_kind(prompt: str) -> str | None:
    low = prompt.lower()
    if any(k in low for k in ("concave", "convex", "mirror", "reflection", "darpan")):
        return "mirror"
    if any(k in low for k in ("lens", "prism", "refraction", "light ray", "ray of light")):
        return "optics"
    if any(k in low for k in ("cell", "mitochondria", "photosynthesis", "dna")):
        return "bio"
    return None


def _draw_sketch(
    draw: ImageDraw.ImageDraw,
    kind: str | None,
    w: int,
    h: int,
    t: float,
    total: float,
    ox: int = 0,
    oy: int = 0,
) -> None:
    """Simple classroom-style schematic (not photorealistic) so clips feel like a lesson, not wallpaper."""
    phase = (t / max(total, 0.001)) * math.pi * 2
    cx, cy = int(w * 0.28) + ox, int(h * 0.28) + oy
    panel = (24 + ox, 24 + oy, int(w * 0.52) + ox, int(h * 0.52) + oy)
    draw.rounded_rectangle(panel, radius=18, outline=(220, 230, 255), width=3)
    draw.text((36, 32), "Idea sketch", fill=(230, 235, 255))

    if kind == "mirror":
        sway = 12 * math.sin(phase)
        # Mirror curve (concave-ish arc)
        bbox = (cx - 90 + sway, cy - 110, cx + 90 + sway, cy + 110)
        draw.arc(bbox, start=200, end=340, fill=(255, 220, 120), width=5)
        # Incident / reflected rays
        for i, ang in enumerate((-0.35, 0.0, 0.35)):
            x1 = cx - 160 + i * 15
            y1 = cy + 40
            x2 = cx - 20 + int(40 * math.sin(phase + i))
            y2 = cy - 10
            draw.line((x1, y1, x2, y2), fill=(120, 200, 255), width=3)
            draw.line((x2, y2, cx + 120, cy - 60 + i * 20), fill=(180, 255, 200), width=3)
        draw.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), fill=(255, 255, 255))
        draw.text((cx - 40, cy + 90), "rays · mirror", fill=(200, 210, 230))
    elif kind == "optics":
        draw.ellipse((cx - 100, cy - 30, cx + 100, cy + 30), outline=(150, 220, 255), width=4)
        for i in range(3):
            y = cy - 40 + i * 40
            draw.line((cx - 180, y, cx - 110, cy), fill=(255, 200, 120), width=2)
            draw.line((cx + 110, cy, cx + 200, y + 20), fill=(120, 255, 200), width=2)
        draw.text((cx - 50, cy + 55), "lens / rays", fill=(200, 210, 230))
    elif kind == "bio":
        draw.rounded_rectangle((cx - 80, cy - 50, cx + 80, cy + 50), radius=30, outline=(160, 255, 180), width=3)
        draw.text((cx - 55, cy - 10), "cell idea", fill=(200, 240, 210))
        draw.line((cx - 120, cy, cx - 85, cy), fill=(255, 220, 150), width=2)
    else:
        # Generic: moving nodes + arrow (concept map feel)
        n = 3
        for i in range(n):
            px = 80 + i * 120 + int(10 * math.sin(phase + i))
            py = cy + int(8 * math.cos(phase * 0.8 + i))
            r = 22
            draw.ellipse((px - r, py - r, px + r, py + r), outline=(140, 190, 255), width=2)
            if i < n - 1:
                draw.line((px + r, py, px + 120 - r, py + int(6 * math.sin(phase))), fill=(120, 160, 220), width=2)
        draw.text((60, panel[3] - 36), "concepts", fill=(190, 200, 220))


def _render_frame(text: str, w: int, h: int, t: float, total: float, sketch_kind: str | None) -> np.ndarray:
    x = np.linspace(0, 1, w, dtype=np.float32)
    y = np.linspace(0, 1, h, dtype=np.float32)
    xv, yv = np.meshgrid(x, y)
    phase = t / max(total, 1.0)
    r = (25 + 85 * np.sin((xv + phase) * np.pi)).clip(0, 255)
    g = (35 + 95 * np.cos((yv + phase * 1.25) * np.pi)).clip(0, 255)
    b = (85 + 105 * np.sin((xv * 0.5 + yv + phase * 0.65) * np.pi)).clip(0, 255)
    arr = np.stack([r, g, b], axis=-1).astype(np.uint8)

    img = Image.fromarray(arr)
    draw = ImageDraw.Draw(img)
    _draw_sketch(draw, sketch_kind, w, h, t, total)

    font, font_small = _load_font_pair()

    pulse = 1.0 + 0.02 * math.sin(phase * math.pi * 2)
    box_w = int(w * 0.82 * pulse)
    left = (w - box_w) // 2
    top = int(h * 0.58)
    box_h = min(200, h - top - 28)
    draw.rounded_rectangle((left, top, left + box_w, top + box_h), radius=22, fill=(12, 16, 28))

    draw.text((left + 16, top + 10), "On-screen notes", fill=(160, 175, 205), font=font_small)

    words = text.split()
    lines: list[str] = []
    curr = ""
    for word in words:
        trial = (curr + " " + word).strip()
        if len(trial) > 48:
            lines.append(curr)
            curr = word
        else:
            curr = trial
    if curr:
        lines.append(curr)

    y0 = top + 38
    for ln in lines[:4]:
        draw.text((left + 22, y0), ln, fill=(245, 248, 255), font=font)
        y0 += 46

    return np.array(img)


def _gradient_bg_motion(w: int, h: int, t: float, total: float) -> np.ndarray:
    x = np.linspace(0, 1, w, dtype=np.float32)
    y = np.linspace(0, 1, h, dtype=np.float32)
    xv, yv = np.meshgrid(x, y)
    phase = t / max(total, 1.0)
    swirl = 0.35 * np.sin((xv * 3.2 + yv * 2.1 + phase * 0.8) * np.pi)
    r = (18 + 72 * np.cos((xv + phase) * np.pi * 2 + swirl)).clip(0, 255)
    g = (28 + 68 * np.sin((yv * 1.3 - phase * 1.1) * np.pi)).clip(0, 255)
    b = (55 + 120 * np.sin((xv * 0.6 + yv * 1.4 + phase * 0.5) * np.pi)).clip(0, 255)
    arr = np.stack([r, g, b], axis=-1).astype(np.uint8)
    cx, cy = w / 2, h / 2
    yy, xx = np.ogrid[:h, :w]
    dist = np.sqrt((xx - cx) ** 2 / (w * 0.48) ** 2 + (yy - cy) ** 2 / (h * 0.48) ** 2)
    vig = (1.0 - 0.35 * np.clip(dist, 0, 1) ** 1.2).astype(np.float32)[..., None]
    return (arr.astype(np.float32) * vig).clip(0, 255).astype(np.uint8)


def _ken_burns_apply(img: Image.Image, out_w: int, out_h: int, t: float, total: float) -> Image.Image:
    w, h = img.size
    phase = (t / max(total, 0.001)) * math.pi * 2
    zoom = 1.0 + 0.085 * math.sin(phase * 0.7)
    cx = w / 2 + 55 * math.sin(phase * 0.35)
    cy = h / 2 + 38 * math.cos(phase * 0.28)
    rw = max(2, int(w / zoom))
    rh = max(2, int(h / zoom))
    left = int(cx - rw / 2)
    top = int(cy - rh / 2)
    left = max(0, min(left, w - rw))
    top = max(0, min(top, h - rh))
    cropped = img.crop((left, top, left + rw, top + rh))
    return cropped.resize((out_w, out_h), Image.Resampling.LANCZOS)


def _wrap_text_words(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    curr = ""
    for word in words:
        trial = (curr + " " + word).strip()
        if len(trial) > max_chars:
            if curr:
                lines.append(curr)
            curr = word
        else:
            curr = trial
    if curr:
        lines.append(curr)
    return lines[:4]


def _render_frame_motion_plus(
    text: str,
    out_w: int,
    out_h: int,
    t: float,
    total: float,
    sketch_kind: str | None,
    local_u: float,
) -> np.ndarray:
    ow, oh = 1520, 855
    bg = _gradient_bg_motion(ow, oh, t, total)
    img = Image.fromarray(bg)
    draw = ImageDraw.Draw(img)
    ox = int(22 * math.sin((t / max(total, 0.001)) * math.pi * 2.8))
    oy = int(14 * math.cos((t / max(total, 0.001)) * math.pi * 2.3))
    _draw_sketch(draw, sketch_kind, ow, oh, t, total, ox=ox, oy=oy)

    for k in range(14):
        ph = t * 1.15 + k * 0.55
        px = int(ow * (0.06 + 0.065 * (k % 11)) + 18 * math.sin(ph))
        py = int(oh * 0.1 + 12 * math.cos(ph))
        r = 2 + (k % 3)
        draw.ellipse((px - r, py - r, px + r, py + r), fill=(210, 220, 245))

    font, font_small = _load_font_pair()
    ease = 1.0 - (1.0 - min(1.0, max(0.0, local_u))) ** 2
    y_slide = int((1.0 - ease) * 30)
    alpha_f = min(1.0, local_u * 4.5)
    pulse = 1.0 + 0.018 * math.sin((t / max(total, 0.001)) * math.pi * 4)
    box_w = int(ow * 0.82 * pulse)
    left = (ow - box_w) // 2
    top = int(oh * 0.56) + y_slide
    box_h = min(220, oh - top - 32)
    draw.rounded_rectangle((left, top, left + box_w, top + box_h), radius=22, fill=(10, 14, 26))
    draw.text((left + 16, top + 10), "On-screen notes", fill=(130, 148, 178), font=font_small)
    lines = _wrap_text_words(text, 52)
    y0 = top + 40
    br = int(18 + 227 * alpha_f)
    fill_main = (min(255, br + 8), min(255, br + 10), 255)
    for ln in lines[:4]:
        draw.text((left + 22, y0), ln, fill=fill_main, font=font)
        y0 += 48

    cropped = _ken_burns_apply(img, out_w, out_h, t, total)
    return np.array(cropped)


async def create_job(
    prompt: str,
    seconds: int,
    animation_preset: Literal["classic", "motion_plus"] = "classic",
) -> LocalVideoJob:
    jid = f"osvid_{uuid.uuid4().hex[:12]}"
    job = LocalVideoJob(
        id=jid,
        seconds=str(seconds),
        model=_model_label(animation_preset),
    )
    async with _lock:
        _jobs[jid] = job

    asyncio.create_task(_run_job(job, prompt, seconds, animation_preset))
    return job


async def _run_job(
    job: LocalVideoJob,
    prompt: str,
    seconds: int,
    preset: Literal["classic", "motion_plus"],
) -> None:
    try:
        job.status = "in_progress"
        w, h = 1280, 720
        lines = _split_lines(prompt)
        sketch = _detect_sketch_kind(prompt)

        if preset == "motion_plus":
            fps = 24
        else:
            fps = 12
        total_frames = max(1, int(seconds * fps))

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp:
            out_path = Path(tmp.name)

        writer = imageio.get_writer(
            str(out_path),
            format="FFMPEG",
            mode="I",
            fps=float(fps),
            codec="libx264",
            ffmpeg_params=["-pix_fmt", "yuv420p"],
        )
        n_lines = max(len(lines), 1)
        for i in range(total_frames):
            t_abs = i / fps
            if preset == "motion_plus":
                u = i / max(total_frames - 1, 1)
                seg_len = 1.0 / n_lines
                seg_idx = min(n_lines - 1, int(u / seg_len))
                seg_start = seg_idx * seg_len
                local_u = (u - seg_start) / seg_len if seg_len > 0 else 1.0
                local_u = max(0.0, min(1.0, local_u))
                line = lines[seg_idx]
                frame = _render_frame_motion_plus(line, w, h, t_abs, float(seconds), sketch, local_u)
            else:
                idx = min(len(lines) - 1, int((i / total_frames) * len(lines)))
                frame = _render_frame(lines[idx], w, h, t_abs, float(seconds), sketch)
            writer.append_data(frame)
            if i % max(1, total_frames // 20) == 0:
                job.progress = i / total_frames
                await asyncio.sleep(0)
        writer.close()

        job.bytes_data = out_path.read_bytes()
        out_path.unlink(missing_ok=True)
        job.progress = 1.0
        job.status = "completed"
    except Exception as e:  # noqa: BLE001
        job.status = "failed"
        job.error = {"code": "opensource_video_failed", "message": str(e)}


async def get_job(video_id: str) -> LocalVideoJob:
    async with _lock:
        if video_id not in _jobs:
            raise ValueError(f"Unknown open-source video id: {video_id}")
        return _jobs[video_id]


async def get_video_bytes(video_id: str) -> bytes:
    job = await get_job(video_id)
    if job.status != "completed" or not job.bytes_data:
        raise ValueError("Video not ready")
    return job.bytes_data
