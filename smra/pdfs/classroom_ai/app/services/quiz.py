import json
import re

from pydantic import ValidationError

from app.schemas.language import OutputLanguage
from app.schemas.quiz import QuizGenerateResponse, QuizQuestion
from app.services.llm.factory import get_llm_provider
from app.services.llm.types import Message


def _lang_rule(lang: OutputLanguage) -> str:
    if lang == "english":
        return "All learner-facing text must be in English."
    if lang == "hindi":
        return "All learner-facing text must be in Hindi (Devanagari script)."
    return "All learner-facing text must be in Roman Hindi (Latin letters only, no Devanagari)."


def _prompt(*, topic: str, difficulty: str, question_count: int, output_language: OutputLanguage, context_text: str | None) -> str:
    context = (context_text or "").strip()
    ctx_excerpt = context[:26000]
    grounded = (
        "\nCONTEXT-GROUNDING (mandatory when Context material is non-empty):\n"
        "- Read the Context material carefully. Every question MUST test understanding of that text.\n"
        "- ALL FOUR OPTIONS must be taken from the Context: either exact quotes, or a tight paraphrase "
        "of a sentence/phrase that appears there. Do not invent facts that are not supported by the Context.\n"
        "- WRONG answers must still be real statements from (or clearly implied by) the Context, but they must "
        "NOT correctly answer the question (e.g. true facts about a different sub-point, or a misapplied formula).\n"
        "- In option_explanations, briefly cite which part of the Context each option relates to.\n"
        "- If the Context is too short to build four grounded options, say so by returning fewer questions "
        "only if unavoidable; prefer quoting distinct lines from the Context.\n"
    )
    base = (
        "You are an expert teacher. Generate high-quality MCQ quiz questions.\n"
        f"Topic label (for orientation only; questions must follow the Context): {topic}\n"
        f"Difficulty: {difficulty}\n"
        f"Question count: {question_count}\n"
        f"{_lang_rule(output_language)}\n\n"
        + (grounded if ctx_excerpt else "")
        + "Return JSON only (no markdown) with keys: topic, output_language_used, questions.\n"
        "Each question object must contain: id, question, options (4 options), correct_option_index (0..3), "
        "correct_explanation, wrong_explanation, option_explanations (length 4; short reason per option).\n"
        "Ensure exactly one correct option per question. Make distractors plausible.\n"
        "IMPORTANT RULES:\n"
        "- Return EXACTLY the requested number of questions.\n"
        "- Each question stem must ask about a *specific fact, definition, step, or contrast* from the "
        "Context (not generic prompts like 'which statement is most closely about the topic').\n"
        "- No repeated questions.\n"
        "- No repeated option sets across questions.\n"
        "- Each option must be a complete claim or answer (not labels about answers).\n"
        "- NEVER use meta-labels like: 'partly incorrect statement', 'unrelated statement', "
        "'contradictory statement', 'Option 1', or any option that only describes the *type* of answer.\n"
        "- Use the Context material as the only source of facts when it is provided.\n"
        + (f"\n\nContext material:\n{ctx_excerpt}" if ctx_excerpt else "")
    )
    return base


def _words(s: str) -> set[str]:
    return set(re.findall(r"[\w]{3,}", s.lower()))


def _sentences_from_context(text: str, *, min_len: int = 15) -> list[str]:
    parts = re.split(r"(?<=[.!?।])\s+|\n+", text)
    out: list[str] = []
    seen: set[str] = set()
    for p in parts:
        s = " ".join(p.split())
        if len(s) < min_len:
            continue
        key = s.lower()[:120]
        if key in seen:
            continue
        seen.add(key)
        out.append(s[:300])
    # Split long comma-separated clauses for more candidates
    if len(out) < 6:
        extra: list[str] = []
        for s in list(out):
            for part in re.split(r"(?<=[,;:])\s+", s):
                p = part.strip()
                if min_len <= len(p) <= 300:
                    k = p.lower()[:100]
                    if k not in seen:
                        seen.add(k)
                        extra.append(p)
        out.extend(extra)
    return out


def _option_grounded(option: str, context: str) -> bool:
    o = option.strip()
    if len(o) < 10:
        return False
    ol = o.lower()
    ctx = context.lower()
    if len(o) >= 18 and ol in ctx:
        return True
    for win in (40, 32, 24):
        for i in range(0, max(1, len(o) - win + 1), 6):
            chunk = ol[i : i + win]
            if len(chunk) >= 18 and chunk in ctx:
                return True
    ow = _words(o)
    if len(ow) < 4:
        return False
    best = 0
    for sent in _sentences_from_context(context, min_len=12):
        inter = len(ow & _words(sent))
        if inter > best:
            best = inter
    return best >= max(3, int(0.22 * len(ow)))


def _option_soft_overlap(option: str, context: str) -> bool:
    """True if enough content words from the option appear in the context (accepts paraphrases)."""
    ow = _words(option)
    cw = _words(context)
    if len(ow) < 3:
        return False
    inter = len(ow & cw)
    return inter >= max(3, int(0.2 * len(ow)))


def _question_overlaps_context(question: str, context: str, *, min_shared: int = 3) -> bool:
    qwl = _words(question)
    cwl = _words(context)
    if len(qwl & cwl) >= min_shared:
        return True
    qn = " ".join(question.lower().split())[:200]
    return len(qn) >= 24 and qn in context.lower()


def _wrong_claims_from_sentence(s: str, topic: str) -> list[str]:
    """Three plausible-but-wrong options derived from a real sentence (no template meta-phrases)."""
    s = s.strip()
    if len(s) < 15:
        return [
            f"The main ideas of {topic} are unrelated to observations in experiments.",
            f"Students can ignore definitions when studying {topic}.",
            f"{topic} has no standard terminology in textbooks.",
        ]
    a = re.sub(r"\bis\b", "is not", s, count=1, flags=re.IGNORECASE)
    if a.lower() == s.lower():
        a = re.sub(r"\bequals\b", "does not equal", s, count=1, flags=re.IGNORECASE)
    if a.lower() == s.lower():
        a = ("It is false that " + s[0].lower() + s[1:]) if len(s) > 1 else "False: " + s
    b = s.rstrip(".!?") + "; however, the lesson text rejects this exact claim."
    c = s[: max(20, len(s) // 2)].rstrip() + " … [misstated] " + "the chapter describes a different relationship."
    out = [a[:300], b[:300], c[:300]]
    seen: set[str] = {s.lower()}
    deduped: list[str] = []
    for o in out:
        k = o.lower()
        if k not in seen:
            seen.add(k)
            deduped.append(o)
    n = 0
    while len(deduped) < 3:
        n += 1
        deduped.append(f"A common exam mistake about {topic} is to confuse this with an unrelated law ({n}).")
    return deduped[:3]


def _best_sentence_index_for_topic(topic: str, sentences: list[str]) -> int:
    tw = _words(topic)
    best_i, best = 0, -1
    for i, s in enumerate(sentences):
        sc = len(tw & _words(s))
        if sc > best:
            best, best_i = sc, i
    return best_i if best > 0 else 0


def _fallback_context_sentence_quiz(topic: str, idx: int, context_text: str) -> QuizQuestion | None:
    """Four options are distinct lines from the lesson; correct = best aligned with topic label."""
    sents = _sentences_from_context(context_text, min_len=15)
    if len(sents) < 4:
        return None
    # Pick a window of 4 unique sentences, rotate by idx
    start = idx % max(1, len(sents) - 3)
    chunk = sents[start : start + 4]
    if len(chunk) < 4:
        chunk = (sents + sents)[:4]
    corr_sent = chunk[_best_sentence_index_for_topic(topic, chunk)]
    others = [s for s in chunk if s[:90].lower() != corr_sent[:90].lower()][:3]
    while len(others) < 3:
        for s in sents:
            if s[:90].lower() != corr_sent[:90].lower() and all(s[:90].lower() != o[:90].lower() for o in others):
                others.append(s)
                if len(others) >= 3:
                    break
        if len(others) < 3:
            break
    if len(others) < 3:
        return None

    correct_idx = idx % 4
    options = [""] * 4
    options[correct_idx] = corr_sent
    slots = [i for i in range(4) if i != correct_idx]
    for slot, o in zip(slots, others[:3]):
        options[slot] = o

    n = idx + 1
    stems = (
        "[{n}] According to the lesson, which statement best matches «{t}»?",
        "[{n}] Which line from the text is most directly about «{t}»?",
        "[{n}] Based only on the passage, which choice aligns best with «{t}»?",
        "[{n}] The lesson includes several ideas. Which option is most relevant to «{t}»?",
    )
    tlab = topic.strip() or "this topic"
    stem = stems[idx % len(stems)].format(n=n, t=tlab)
    return QuizQuestion(
        id=f"q{n}",
        question=stem,
        options=options,
        correct_option_index=correct_idx,
        correct_explanation="This line matches the lesson and fits the topic best among the choices.",
        wrong_explanation="Another line is a better match, or this line is about a different detail.",
        option_explanations=["Best topic match from the text."] * 4,
    )


def _fallback_question(topic: str, idx: int, context_text: str | None) -> QuizQuestion:
    ctx = (context_text or "").strip()
    if ctx:
        cq = _fallback_context_sentence_quiz(topic, idx, ctx)
        if cq is not None:
            oex = [
                (
                    "Pulled from your lesson text; compare wording to the chapter."
                    if j == cq.correct_option_index
                    else "Also from the lesson, but not the best answer to this question."
                )
                for j in range(4)
            ]
            return cq.model_copy(update={"option_explanations": oex})

    sents = _sentences_from_context(ctx) if ctx else []
    n = idx + 1
    correct_idx = idx % 4

    if sents:
        base = sents[idx % len(sents)]
        wrong = _wrong_claims_from_sentence(base, topic)
        options = [""] * 4
        options[correct_idx] = base
        slots = [i for i in range(4) if i != correct_idx]
        for slot, w in zip(slots, wrong):
            options[slot] = w
        qtext = (
            f"[{n}] According to the lesson text, which statement is faithful to what it says about "
            f"«{topic}»?"
        )
        return QuizQuestion(
            id=f"q{n}",
            question=qtext,
            options=options,
            correct_option_index=correct_idx,
            correct_explanation="This option matches the lesson wording; the others change or negate it.",
            wrong_explanation="Compare each line to the chapter: three options are distorted.",
            option_explanations=[
                "Matches the lesson sentence." if j == correct_idx else "Alters or contradicts the lesson."
                for j in range(4)
            ],
        )

    return QuizQuestion(
        id=f"q{n}",
        question=f"[{n}] For «{topic}», what do textbooks usually expect you to know first?",
        options=[
            f"Key terms, definitions, and how they connect within {topic}.",
            f"Unrelated trivia that never appears in {topic} chapters.",
            f"That {topic} is never assessed in exams.",
            f"That you should skip diagrams when studying {topic}.",
        ],
        correct_option_index=0,
        correct_explanation="Definitions and relationships are the usual foundation.",
        wrong_explanation="The other choices are not serious study goals.",
        option_explanations=[
            "Standard study approach.",
            "Not a serious distractor.",
            "Not a serious distractor.",
            "Not a serious distractor.",
        ],
    )


_BOILERPLATE_SUBSTR = (
    "partly incorrect statement mixing",
    "unrelated statement that does not explain",
    "contradictory statement about",
    "conceptually correct statement about",
)


def _looks_like_boilerplate_options(options: list[str]) -> bool:
    joined = " ".join(o.lower() for o in options)
    return any(b in joined for b in _BOILERPLATE_SUBSTR)


def _question_needs_fallback(q: QuizQuestion, context_text: str | None) -> bool:
    opts = [o.strip() for o in (q.options or []) if o and o.strip()]
    ctx = (context_text or "").strip()
    if len(opts) < 4:
        return True
    if _looks_like_boilerplate_options(opts):
        return True
    if len({o.lower() for o in opts}) < 4:
        return True
    if any(re.match(r"^option\s*\d+\s*$", o, re.I) for o in opts):
        return True
    if not ctx:
        return False

    hard = sum(1 for o in opts if _option_grounded(o, ctx))
    soft = sum(1 for o in opts if _option_soft_overlap(o, ctx))
    q_ok = _question_overlaps_context(q.question, ctx, min_shared=3)

    # Requiring all four options to match the text literally rejected good paraphrases and
    # forced the same template question repeatedly (only options changed).
    if hard >= 2:
        return False
    if hard >= 1 and q_ok:
        return False
    if soft >= 3 and q_ok:
        return False
    if soft >= 2 and hard >= 1:
        return False
    if hard == 0 and soft <= 1:
        return True
    return False


def _normalize_questions(
    parsed: QuizGenerateResponse,
    topic: str,
    question_count: int,
    context_text: str | None,
) -> QuizGenerateResponse:
    qs: list[QuizQuestion] = []
    seen_q: set[str] = set()
    for i, q in enumerate(parsed.questions):
        options = [o.strip() for o in (q.options or [])[:4] if o and o.strip()]
        if len(options) < 4:
            options += [f"Option {j}" for j in range(len(options) + 1, 5)]
        deduped: list[str] = []
        seen_opt: set[str] = set()
        for opt in options:
            key = opt.lower().strip()
            if key not in seen_opt:
                seen_opt.add(key)
                deduped.append(opt)
        options = deduped[:4]
        if len(options) < 4:
            options += [f"Option {j}" for j in range(len(options) + 1, 5)]

        q_key = q.question.lower().strip()
        if not q_key or q_key in seen_q:
            continue
        seen_q.add(q_key)

        idx = q.correct_option_index if 0 <= q.correct_option_index < 4 else 0
        oex = q.option_explanations[:4] if q.option_explanations else None
        if oex is not None and len(oex) < 4:
            oex += [q.wrong_explanation] * (4 - len(oex))

        built = q.model_copy(
            update={
                "id": f"q{i + 1}",
                "options": options,
                "correct_option_index": idx,
                "option_explanations": oex,
            }
        )
        if _question_needs_fallback(built, context_text):
            built = _fallback_question(topic, i, context_text).model_copy(update={"id": f"q{i + 1}"})
        qs.append(built)

    while len(qs) < question_count:
        qs.append(_fallback_question(topic, len(qs), context_text))

    return parsed.model_copy(update={"questions": qs[:question_count]})


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
        chunk = raw[start : end + 1]
        try:
            obj = json.loads(chunk)
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


async def generate_quiz(
    *,
    topic: str,
    context_text: str | None,
    output_language: OutputLanguage,
    question_count: int,
    difficulty: str,
    llm_provider: str,
) -> QuizGenerateResponse:
    provider = get_llm_provider(vision=False, provider=llm_provider)
    collected: list[QuizQuestion] = []
    seen: set[str] = set()
    ctx = (context_text or "").strip()
    temp = 0.22 if ctx else 0.42
    max_tok = 9000 if ctx else 5000

    for attempt in range(3):
        remaining = question_count - len(collected)
        if remaining <= 0:
            break

        avoid = ""
        if collected:
            prev = [q.question for q in collected]
            avoid = "\nAlready generated questions (do NOT repeat):\n- " + "\n- ".join(prev[:20])

        messages: list[Message] = [
            {
                "role": "system",
                "content": (
                    "You output strict JSON only. When CONTEXT is provided, every question and all four "
                    "options must be grounded in that CONTEXT (quotes or tight paraphrases)."
                ),
            },
            {
                "role": "user",
                "content": _prompt(
                    topic=topic,
                    difficulty=difficulty,
                    question_count=remaining,
                    output_language=output_language,
                    context_text=context_text,
                )
                + avoid
                + f"\nAttempt: {attempt + 1}",
            },
        ]

        raw = await provider.complete_chat(messages, max_tokens=max_tok, temperature=temp)
        data = _extract_json_obj(raw) or {}
        try:
            parsed_try = QuizGenerateResponse.model_validate(
                {
                    "topic": data.get("topic", topic),
                    "output_language_used": data.get("output_language_used", output_language),
                    "questions": data.get("questions", []),
                }
            )
        except ValidationError:
            parsed_try = QuizGenerateResponse(
                topic=topic,
                output_language_used=output_language,
                questions=[],
            )

        normalized_try = _normalize_questions(
            parsed_try, topic=topic, question_count=max(len(parsed_try.questions), 1), context_text=context_text
        )
        for q in normalized_try.questions:
            key = q.question.lower().strip()
            if key and key not in seen:
                seen.add(key)
                collected.append(q)
                if len(collected) >= question_count:
                    break

    parsed = QuizGenerateResponse(
        topic=topic,
        output_language_used=output_language,
        questions=collected,
    )
    parsed = parsed.model_copy(update={"output_language_used": output_language, "topic": topic})
    return _normalize_questions(parsed, topic, question_count, context_text)
