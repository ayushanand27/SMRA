import json

from pydantic import ValidationError

from app.schemas.flashcards import FlashcardItem, FlashcardsResponse
from app.schemas.language import OutputLanguage, normalize_output_language
from app.services.llm.factory import get_llm_provider
from app.services.llm.types import Message


def _lang_rule(lang: OutputLanguage) -> str:
    if lang == "english":
        return "All flashcard text must be in English."
    if lang == "hindi":
        return "All flashcard text must be in Hindi (Devanagari script)."
    return "All flashcard text must be in Roman Hindi (Latin letters only, no Devanagari)."


def _prompt(*, topic: str, card_count: int, output_language: OutputLanguage, context_text: str | None) -> str:
    ctx = (context_text or "").strip()[:26000]
    return (
        "You create study flashcards like NotebookLM: concise term or question on the front, clear answer on the back.\n"
        f"Topic: {topic}\n"
        f"Number of cards: {card_count}\n"
        f"{_lang_rule(output_language)}\n\n"
        "Return JSON only with keys: topic, cards.\n"
        "cards is an array of objects: {front, back}. No markdown inside strings.\n"
        "- Front: short cue (term, \"What is…?\", or fill-in stem).\n"
        "- Back: definition, explanation, or answer (can be 1–3 short sentences).\n"
        "- Ground cards in the Context when provided; avoid generic filler.\n"
        "- Cards must be distinct.\n"
        + (f"\nContext material:\n{ctx}\n" if ctx else "")
    )


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


def _normalize_cards(data: dict, topic: str, card_count: int, lang: OutputLanguage) -> list[FlashcardItem]:
    raw = data.get("cards")
    if not isinstance(raw, list):
        raw = []
    out: list[FlashcardItem] = []
    for i, item in enumerate(raw[:card_count]):
        if not isinstance(item, dict):
            continue
        f = str(item.get("front", "")).strip()[:500]
        b = str(item.get("back", "")).strip()[:2000]
        if len(f) < 2 or len(b) < 2:
            continue
        try:
            out.append(FlashcardItem(front=f, back=b))
        except ValidationError:
            continue
    while len(out) < min(card_count, 4):
        n = len(out) + 1
        out.append(
            FlashcardItem(
                front=f"Key idea {n} — {topic}",
                back="Review this point in your chapter and add your own example.",
            )
        )
    return out[:card_count]


async def generate_flashcards(
    *,
    topic: str,
    context_text: str | None,
    output_language: str,
    card_count: int,
    llm_provider: str,
) -> FlashcardsResponse:
    lang = normalize_output_language(output_language)
    provider = get_llm_provider(vision=False, provider=llm_provider)
    messages: list[Message] = [
        {"role": "system", "content": "You output strict JSON only."},
        {
            "role": "user",
            "content": _prompt(topic=topic, card_count=card_count, output_language=lang, context_text=context_text),
        },
    ]
    raw = await provider.complete_chat(messages, max_tokens=8000, temperature=0.35)
    data = _extract_json_obj(raw) or {}
    cards = _normalize_cards(data, topic=topic, card_count=card_count, lang=lang)
    return FlashcardsResponse(
        topic=str(data.get("topic", topic))[:200],
        output_language_used=lang,
        cards=cards,
    )
