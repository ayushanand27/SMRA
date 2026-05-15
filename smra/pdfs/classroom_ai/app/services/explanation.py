import asyncio
import base64
import json
import re

from pydantic import ValidationError

from app.core.config import get_settings
from app.schemas.explain import ExplainResponse, VisualAssetBrief
from app.schemas.language import OutputLanguage
from app.services import illustration_openai, illustration_opensource
from app.services.llm.factory import get_llm_provider
from app.services.llm.types import ImageUrlPart, Message, TextPart
from app.services.pdf_extract import extract_pdf_to_text


def _user_language_block(output_language: OutputLanguage, *, closing: bool = False) -> str:
    """Strong, repeated instructions; JSON schema examples were biasing models toward English."""
    if output_language == "english":
        line = "OUTPUT_LANGUAGE=english. All learner-facing strings must be in English."
    elif output_language == "hindi":
        line = (
            "OUTPUT_LANGUAGE=hindi (Devanagari). All learner-facing strings — explanation_markdown, "
            "simple_examples, visual_brief title/description, suggested_followup_topics, "
            "video_lesson_prompt — MUST be in Hindi using देवनागरी script. "
            "Do not use Roman/Latin letters for Hindi words. Translate from the chapter if it is in English."
        )
    else:
        line = (
            "OUTPUT_LANGUAGE=roman_hindi (Hindi in Latin letters only). "
            "All learner-facing strings — explanation_markdown, simple_examples, "
            "visual_brief title/description, suggested_followup_topics, video_lesson_prompt — "
            "MUST be Hindi written with A–Z letters only (e.g. \"Prakash ki paravartan\", "
            "\"Darpan par padne wala kon\"). "
            "Do NOT use Devanagari (no Hindi script). "
            "JSON keys stay English; enum tokens kind/suggested_format stay as specified. "
            "Mermaid labels: Roman Hindi or very short English. "
            "Translate the teaching from the chapter even if the chapter is English."
        )
    tag = "FINAL CHECK — " if closing else ""
    return f"{tag}{line}\n\n"


_JSON_CONTRACT = """
Return a single JSON object only (no markdown code fences).
You MUST use the exact key names below. Do not return only book metadata (title, author, publisher, text)
as a substitute — the full lesson must live in explanation_markdown with the other required keys.
Keys (keep these key names in English): explanation_markdown (string), simple_examples (array of strings),
visual_briefs (array of {title, description, kind, suggested_format}),
suggested_followup_topics (array of strings), video_lesson_prompt (string or null), mermaid_diagram (string or null),
diagram_caption (string or null).

Rules:
- explanation_markdown: Must be clear, textbook-style Markdown in OUTPUT_LANGUAGE only. Use this structure (headings in OUTPUT_LANGUAGE):
  * One ## title line for the lesson topic.
  * ### sections in order (skip any that do not apply): Main ideas; Step-by-step (or reasoning); Real-life / numerical examples; Key terms; Quick recap.
  * Use **bold** for important terms, short bullet lists where helpful, short paragraphs (3–6 sentences).
  * Do NOT wrap the whole explanation in a single code block. No English mixed in when OUTPUT_LANGUAGE is hindi or roman_hindi.
- simple_examples: At least 3 items. Each string is ONE concrete example: include numbers/units when the topic allows, or a specific everyday situation (e.g. "If distance is 2 m and …"). Avoid vague one-liners like "study hard".
- kind must be one of: diagram, analogy_illustration, timeline, graph_concept, animation_idea, other.
- suggested_format must be one of: mermaid, animation_storyboard, svg_or_image.
- Put at least 2 items in visual_briefs; use full sentences in title and description.
- mermaid_diagram: valid Mermaid v10+ syntax only, or null. Prefer flowchart TD or graph LR. First line MUST be the diagram keyword (no title line before it). Use ASCII-only node IDs (A, B, C, …). Put ALL label text in double quotes: A["Light source"] --> B["Mirror"]. Use --> for links. Avoid raw parentheses inside unquoted brackets. Do NOT put a second copy of the diagram inside explanation_markdown fenced blocks — only here in mermaid_diagram. Newlines in JSON must be escaped as \\n.
- diagram_caption: If mermaid_diagram is non-null, add 1–3 sentences in OUTPUT_LANGUAGE explaining what the diagram shows (a legend: parts, arrows, or how to read it). If no diagram, use null.

LANGUAGE: Every string that students will read MUST follow OUTPUT_LANGUAGE from the messages above — not English unless OUTPUT_LANGUAGE is english.
"""


def _system_prompt(output_language: OutputLanguage, topic_hint: str | None) -> str:
    focus = f" Focus the explanation on: {topic_hint}." if topic_hint else ""
    if output_language == "english":
        lang = "Learner-facing text: English only."
    elif output_language == "hindi":
        lang = "Learner-facing text: Hindi in Devanagari only (देवनागरी)."
    else:
        lang = "Learner-facing text: Roman Hindi only (Hindi in Latin alphabet, no Devanagari)."
    return (
        "You are an expert school teacher. Simplify the chapter for students using clear structure, "
        "realistic examples, and language that matches OUTPUT_LANGUAGE exactly.\n"
        f"{lang}{focus}\n"
        "Include at least two visual_briefs: one animation_storyboard and one mermaid when possible.\n"
        "For mermaid_diagram, use classDef to color and style nodes: "
        "classDef main fill:#ffe082,stroke:#333,stroke-width:2px; "
        "classDef asexual fill:#b2dfdb,stroke:#333,stroke-width:2px; "
        "classDef sexual fill:#f8bbd0,stroke:#333,stroke-width:2px; "
        "Assign class main to main concepts, asexual to asexual reproduction nodes, sexual to sexual reproduction nodes. "
        "Use subgraphs to group related nodes if possible. Add icons or emojis for extra clarity if appropriate.\n"
        + _JSON_CONTRACT
    )


_MERMAID_HEADER = re.compile(
    r"^\s*(flowchart|graph|sequenceDiagram|classDiagram|stateDiagram(?:-v2)?|erDiagram|"
    r"gantt|pie|journey|mindmap|timeline|quadrantChart|block-beta|packet-beta)\b",
    re.IGNORECASE | re.MULTILINE,
)


def _strip_mermaid_fences(raw: str | None) -> str | None:
    if not raw or not str(raw).strip():
        return None
    s = str(raw).strip()
    s = re.sub(r"^```mermaid\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^```\s*", "", s)
    s = re.sub(r"\s*```$", "", s)
    return s.strip() or None


def _sanitize_mermaid_diagram(raw: str | None) -> str | None:
    """Drop preamble lines; ensure a Mermaid diagram keyword starts the chart (v11 is strict)."""
    md = _strip_mermaid_fences(raw)
    if not md:
        return None
    if "\\n" in md and "\n" not in md:
        md = md.replace("\\n", "\n")
    lines = md.splitlines()
    start = 0
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if _MERMAID_HEADER.match(line):
            start = i
            break
    else:
        body = "\n".join(ln.strip() for ln in lines if ln.strip())
        if not body:
            return None
        return f"flowchart TD\n{body}"
    diagram = "\n".join(lines[start:]).strip()
    if not diagram:
        return None
    # Smart quotes / unicode dashes often break Mermaid 11 parsers in labels.
    diagram = (
        diagram.replace("\u201c", '"')
        .replace("\u201d", '"')
        .replace("\u2018", "'")
        .replace("\u2019", "'")
        .replace("\u200b", "")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
    )
    diagram = _enhance_mermaid_vibrancy(diagram)
    return diagram


_MERMAID_CLASSDEFS = (
    "classDef main fill:#fff3cd,stroke:#8a6d00,stroke-width:2.5px,color:#1f1f1f;",
    "classDef accent1 fill:#d1f7ff,stroke:#0077a6,stroke-width:2.5px,color:#1f1f1f;",
    "classDef accent2 fill:#e7dbff,stroke:#6f42c1,stroke-width:2.5px,color:#1f1f1f;",
    "classDef accent3 fill:#d9fbe2,stroke:#198754,stroke-width:2.5px,color:#1f1f1f;",
    "classDef accent4 fill:#ffd6e7,stroke:#c2185b,stroke-width:2.5px,color:#1f1f1f;",
    "classDef accent5 fill:#ffe8c2,stroke:#d97706,stroke-width:2.5px,color:#1f1f1f;",
)


def _enhance_mermaid_vibrancy(diagram: str) -> str:
    lines = [line for line in diagram.splitlines() if line.strip()]
    if not lines:
        return diagram
    classdef_present = {
        re.match(r"^classDef\s+([A-Za-z0-9_]+)\b", line).group(1)
        for line in lines
        if re.match(r"^classDef\s+([A-Za-z0-9_]+)\b", line)
    }
    if not classdef_present:
        lines.extend(_MERMAID_CLASSDEFS)
        classdef_present = {"main", "accent1", "accent2", "accent3", "accent4", "accent5"}

    node_pattern = re.compile(r"^\s*([A-Za-z0-9_]+)\s*(?:\[|\(|\{|<)")
    class_assignments: list[str] = []
    accent_cycle = ["accent1", "accent2", "accent3", "accent4", "accent5"]
    accent_idx = 0

    for line in lines:
        if line.startswith("classDef ") or line.startswith("class "):
            continue
        m = node_pattern.match(line)
        if not m:
            continue
        node_id = m.group(1)
        label = line.lower()
        if any(word in label for word in ["main", "overview", "summary", "foundation", "core", "central"]):
            class_assignments.append(f"class {node_id} main;")
            continue
        if any(word in label for word in ["process", "step", "flow", "sequence", "stage", "timeline"]):
            cls = accent_cycle[accent_idx % len(accent_cycle)]
            accent_idx += 1
            class_assignments.append(f"class {node_id} {cls};")
            continue
        if any(word in label for word in ["asexual", "binary fission", "budding", "fragmentation", "vegetative"]):
            class_assignments.append(f"class {node_id} accent3;")
            continue
        if any(word in label for word in ["sexual", "gamete", "zygote", "fertilisation", "fertilization"]):
            class_assignments.append(f"class {node_id} accent4;")
            continue
        if any(word in label for word in ["example", "illustration", "analogy", "real-life", "life", "use case"]):
            class_assignments.append(f"class {node_id} accent5;")
            continue
        cls = accent_cycle[accent_idx % len(accent_cycle)]
        accent_idx += 1
        class_assignments.append(f"class {node_id} {cls};")

    if class_assignments:
        lines.extend(class_assignments)

    for cls, classdef in zip(["main", "accent1", "accent2", "accent3", "accent4", "accent5"], _MERMAID_CLASSDEFS):
        if cls not in classdef_present and any(f" {cls}" in assignment for assignment in class_assignments):
            lines.append(classdef)

    return "\n".join(lines)


def _strip_response_json_fences(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```\s*$", "", s)
    return s.strip()


def _extract_json_object(raw: str) -> dict | None:
    """Parse JSON from model output; tolerate leading/trailing prose and fenced blocks."""
    s = _strip_response_json_fences(raw)
    try:
        obj = json.loads(s)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass
    start = s.find("{")
    if start == -1:
        return None
    depth = 0
    for i in range(start, len(s)):
        if s[i] == "{":
            depth += 1
        elif s[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    obj = json.loads(s[start : i + 1])
                    return obj if isinstance(obj, dict) else None
                except json.JSONDecodeError:
                    return None
    return None


_ALLOWED_KIND = frozenset(
    {"diagram", "analogy_illustration", "timeline", "graph_concept", "animation_idea", "other"}
)
_ALLOWED_FORMAT = frozenset({"mermaid", "animation_storyboard", "svg_or_image"})


def _normalize_simple_examples(items: object) -> list[str]:
    if not isinstance(items, list):
        return []
    out = [str(x).strip() for x in items if x is not None and str(x).strip()]
    return out[:24] if out else []


def _normalize_visual_briefs(items: object) -> list[dict]:
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title", "Visual")).strip() or "Visual"
        desc = str(item.get("description", "")).strip() or "See chapter."
        k = str(item.get("kind", "other")).lower()
        if k not in _ALLOWED_KIND:
            k = "other"
        f = str(item.get("suggested_format", "svg_or_image")).lower()
        if f not in _ALLOWED_FORMAT:
            f = "svg_or_image"
        entry: dict = {"title": title[:400], "description": desc[:4000], "kind": k, "suggested_format": f}
        src = item.get("src")
        if isinstance(src, str) and src.strip():
            entry["src"] = src.strip()
        md = item.get("mermaid_diagram")
        if isinstance(md, str) and md.strip():
            entry["mermaid_diagram"] = md.strip()
        out.append(entry)
    return out


def _visual_brief_defaults() -> list[dict]:
    return [
        {
            "title": "Main concept diagram",
            "description": "A diagram linking the central ideas from the chapter for quick review.",
            "kind": "diagram",
            "suggested_format": "mermaid",
        },
        {
            "title": "Process or storyboard",
            "description": "A short animation-style sequence showing how the main process unfolds step by step.",
            "kind": "animation_idea",
            "suggested_format": "animation_storyboard",
        },
        {
            "title": "Relatable everyday illustration",
            "description": "A vivid classroom-friendly image that connects the chapter idea to a familiar real-world scene.",
            "kind": "analogy_illustration",
            "suggested_format": "svg_or_image",
        },
    ]


def _brief_image_prompt(brief: dict, topic_hint: str | None, output_language: OutputLanguage) -> str:
    title = str(brief.get("title", "Visual")).strip() or "Visual"
    desc = str(brief.get("description", "See chapter.")).strip() or "See chapter."
    topic = f"Lesson topic hint: {topic_hint}. " if topic_hint else ""
    lang_note = ""
    if output_language == "hindi":
        lang_note = "The lesson is in Hindi, but the image should use no readable text. "
    elif output_language == "roman_hindi":
        lang_note = "The lesson is in Roman Hindi, but the image should use no readable text. "
    return (
        f"Create one vibrant educational illustration for a school lesson. {topic}{lang_note}"
        f"Subtopic title: {title}. Subtopic description: {desc}. "
        "Use a clean composition, bright classroom-friendly colors, clear focal subject, subtle depth, no text, no labels, no watermark, no logo, and no clutter."
    )


def _brief_style_suffix(brief: dict) -> str:
    kind = str(brief.get("kind", "other")).lower()
    suggested_format = str(brief.get("suggested_format", "svg_or_image")).lower()
    if suggested_format == "mermaid":
        return "educational infographic poster, vivid flat vector style, no text, crisp edges"
    if kind == "animation_idea":
        return "dynamic storyboard frame, motion hints, colorful classroom illustration, no text"
    if kind == "timeline":
        return "timeline-style educational illustration with flowing panels and icons, no text"
    if kind == "graph_concept":
        return "clean graph-inspired educational poster with bold color blocks and icons, no text"
    if kind == "analogy_illustration":
        return "relatable everyday analogy illustration, vivid and symbolic, no text"
    return "bright school-friendly educational illustration, balanced composition, no text"


async def _generate_brief_image(
    settings,
    *,
    brief: dict,
    topic_hint: str | None,
    output_language: OutputLanguage,
    llm_provider: str | None,
) -> tuple[str, str] | None:
    prompt = _brief_image_prompt(brief, topic_hint, output_language)
    style_suffix = _brief_style_suffix(brief)
    generator = illustration_openai.generate_illustration_png_b64
    if llm_provider != "openai":
        generator = illustration_opensource.generate_illustration_png_b64
    try:
        return await generator(settings, prompt=prompt, style_suffix=style_suffix)
    except Exception:
        return None


async def _attach_generated_visual_assets(
    parsed: ExplainResponse,
    *,
    output_language: OutputLanguage,
    topic_hint: str | None,
    llm_provider: str | None,
) -> ExplainResponse:
    briefs = [b.model_copy() for b in parsed.visual_briefs]
    if len(briefs) < 3:
        needed = 3 - len(briefs)
        briefs.extend(VisualAssetBrief.model_validate(item) for item in _visual_brief_defaults()[:needed])

    settings = get_settings()
    tasks: list[tuple[int, asyncio.Task]] = []
    for idx, brief in enumerate(briefs):
        if brief.src:
            continue
        if brief.kind == "diagram" and brief.suggested_format == "mermaid":
            continue
        tasks.append(
            (
                idx,
                asyncio.create_task(
                    _generate_brief_image(
                        settings,
                        brief=brief.model_dump(),
                        topic_hint=topic_hint,
                        output_language=output_language,
                        llm_provider=llm_provider,
                    )
                ),
            )
        )

    if tasks:
        results = await asyncio.gather(*(task for _, task in tasks), return_exceptions=True)
        for (idx, _task), result in zip(tasks, results):
            if isinstance(result, tuple) and result[0]:
                briefs[idx] = briefs[idx].model_copy(update={"src": f"data:{result[1]};base64,{result[0]}"})

    return parsed.model_copy(update={"visual_briefs": briefs})


def _coerce_explain_dict(data: dict) -> dict:
    """Map common wrong shapes (e.g. title+text only) toward the ExplainResponse schema."""
    d = dict(data)
    em = d.get("explanation_markdown")
    if not isinstance(em, str) or not em.strip():
        pieces: list[str] = []
        if isinstance(d.get("title"), str) and d["title"].strip():
            pieces.append(f"## {d['title'].strip()}")
        for key in ("text", "content", "body", "abstract", "summary", "description"):
            val = d.get(key)
            if isinstance(val, str) and val.strip():
                pieces.append(val.strip())
                break
        if pieces:
            d["explanation_markdown"] = "\n\n".join(pieces)
    ex = _normalize_simple_examples(d.get("simple_examples"))
    if len(ex) < 1:
        ex = [
            "State the main idea from the chapter in one sentence.",
            "Give a concrete example that uses one quantity or object from the reading.",
            "Connect one vocabulary term to the rest of the lesson.",
        ]
    d["simple_examples"] = ex
    vb = _normalize_visual_briefs(d.get("visual_briefs"))
    if len(vb) < 3:
        for default in _visual_brief_defaults():
            if len(vb) >= 3:
                break
            if not any(item.get("kind") == default["kind"] and item.get("suggested_format") == default["suggested_format"] for item in vb):
                vb.append(default)
    image_brief_count = sum(1 for item in vb if str(item.get("suggested_format", "")).lower() != "mermaid")
    if image_brief_count < 2:
        for default in _visual_brief_defaults()[1:]:
            if sum(1 for item in vb if str(item.get("suggested_format", "")).lower() != "mermaid") >= 2:
                break
            if not any(item.get("kind") == default["kind"] and item.get("suggested_format") == default["suggested_format"] for item in vb):
                vb.append(default)
    d["visual_briefs"] = vb

    # --- Guarantee at least one diagram per subtopic (visual_brief) ---
    # If a visual_brief is a diagram/mermaid and has no mermaid_diagram, fill it with the main diagram or a placeholder.
    main_mermaid = d.get("mermaid_diagram")
    for b in d["visual_briefs"]:
        if (
            b.get("kind") == "diagram"
            and b.get("suggested_format") == "mermaid"
            and not b.get("mermaid_diagram")
        ):
            # Use the main diagram if present, else a placeholder
            b["mermaid_diagram"] = main_mermaid or "flowchart TD\nA[\"Diagram not available\"]"
    topics = d.get("suggested_followup_topics")
    if not isinstance(topics, list):
        d["suggested_followup_topics"] = []
    else:
        d["suggested_followup_topics"] = [str(t).strip() for t in topics if str(t).strip()][:20]
    if "video_lesson_prompt" not in d:
        d["video_lesson_prompt"] = None
    if "mermaid_diagram" not in d:
        d["mermaid_diagram"] = None
    if "diagram_caption" not in d:
        d["diagram_caption"] = None
    return d


def _fallback_explain_response(raw: str) -> ExplainResponse:
    return ExplainResponse(
        explanation_markdown=raw,
        simple_examples=[],
        visual_briefs=[
            VisualAssetBrief(
                title="Chapter summary",
                description="The model returned non-JSON text; use the markdown above or try again.",
                kind="other",
                suggested_format="svg_or_image",
            )
        ],
        suggested_followup_topics=[],
        video_lesson_prompt=None,
        mermaid_diagram=None,
        diagram_caption=None,
        output_language_used=None,
        pdf_extraction_notes=None,
        source_text_used_for_context=None,
    )


def _parse_explain_json(raw: str) -> ExplainResponse:
    data = _extract_json_object(raw)
    if not data:
        return _fallback_explain_response(raw)
    data = _coerce_explain_dict(data)
    md = data.get("mermaid_diagram")
    if isinstance(md, str):
        data["mermaid_diagram"] = _sanitize_mermaid_diagram(md)
    try:
        parsed = ExplainResponse.model_validate(data)
    except ValidationError:
        return _fallback_explain_response(raw)
    return parsed


def _explain_max_tokens(chapter_len: int) -> int:
    """Long PDF context needs a larger JSON lesson in the reply."""
    if chapter_len > 45_000:
        return 16_384
    if chapter_len > 15_000:
        return 8192
    if chapter_len > 6000:
        return 6144
    return 4096


def _finalize(parsed: ExplainResponse, output_language: OutputLanguage) -> ExplainResponse:
    return parsed.model_copy(update={"output_language_used": output_language})


async def explain_from_pdf_bytes(
    pdf_bytes: bytes,
    *,
    output_language: OutputLanguage,
    topic_hint: str | None,
    llm_provider: str | None,
    ocr_pages: bool,
    ocr_images: bool,
) -> ExplainResponse:
    ext = extract_pdf_to_text(pdf_bytes, ocr_pages=ocr_pages, ocr_images=ocr_images)
    prefix = (
        "[Source: PDF extraction — content from **all extracted pages** is included below (each page starts with "
        "=== Page N ===). Tables appear in [Table …] blocks; text from figures or scans in [Text from image…] or "
        "[Page N — OCR from page image] blocks. Base your lesson on the **entire** excerpt, not only the opening lines.]\n\n"
    )
    out = await explain_from_text(
        prefix + ext.chapter_text,
        output_language=output_language,
        topic_hint=topic_hint,
        llm_provider=llm_provider,
    )
    out = await _attach_generated_visual_assets(
        out,
        output_language=output_language,
        topic_hint=topic_hint,
        llm_provider=llm_provider,
    )
    return out.model_copy(
        update={
            "pdf_extraction_notes": ext.notes,
            "source_text_used_for_context": ext.chapter_text,
        }
    )


async def explain_from_text(
    chapter_text: str,
    *,
    output_language: OutputLanguage,
    topic_hint: str | None,
    llm_provider: str | None = None,
) -> ExplainResponse:
    body = (
        _user_language_block(output_language)
        + "Chapter content (source material; may be any language — translate and explain fully in OUTPUT_LANGUAGE):\n\n"
        + chapter_text.strip()
        + "\n\n"
        + _user_language_block(output_language, closing=True)
    )
    messages: list[Message] = [
        {"role": "system", "content": _system_prompt(output_language, topic_hint)},
        {"role": "user", "content": body},
    ]
    provider = get_llm_provider(vision=False, provider=llm_provider)
    body_len = len(chapter_text.strip())
    raw = await provider.complete_chat(
        messages,
        max_tokens=_explain_max_tokens(body_len),
        temperature=0.35,
    )
    parsed = _finalize(_parse_explain_json(raw), output_language)
    return await _attach_generated_visual_assets(
        parsed,
        output_language=output_language,
        topic_hint=topic_hint,
        llm_provider=llm_provider,
    )


def _guess_mime(header: bytes) -> str:
    if header.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if header.startswith(b"GIF87a") or header.startswith(b"GIF89a"):
        return "image/gif"
    if header.startswith(b"RIFF") and len(header) >= 12 and header[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


async def explain_from_image_bytes(
    files: list[tuple[str, bytes]],
    *,
    output_language: OutputLanguage,
    topic_hint: str | None,
    llm_provider: str | None = None,
) -> ExplainResponse:
    intro = (
        _user_language_block(output_language)
        + "These images are textbook chapter pages. Read them, then explain simply for students. "
        + "All learner-facing strings in your JSON must follow OUTPUT_LANGUAGE. "
        + (f"Emphasize: {topic_hint}. " if topic_hint else "")
        + _JSON_CONTRACT
    )
    closing = _user_language_block(output_language, closing=True)

    content: list[TextPart | ImageUrlPart] = [{"type": "text", "text": intro}]

    for _filename, data in files:
        if not data:
            continue
        mime = _guess_mime(data[:12])
        if mime == "application/octet-stream":
            mime = "image/png"
        b64 = base64.standard_b64encode(data).decode("ascii")
        content.append(
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{b64}"},
            }
        )

    content.append({"type": "text", "text": closing})

    messages: list[Message] = [
        {"role": "system", "content": _system_prompt(output_language, topic_hint)},
        {"role": "user", "content": content},
    ]

    provider = get_llm_provider(vision=True, provider=llm_provider)
    raw = await provider.complete_chat(messages, max_tokens=4096, temperature=0.35)
    parsed = _finalize(_parse_explain_json(raw), output_language)
    return await _attach_generated_visual_assets(
        parsed,
        output_language=output_language,
        topic_hint=topic_hint,
        llm_provider=llm_provider,
    )
