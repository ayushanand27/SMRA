"""LLM-as-judge scoring for answer quality.

Grades a generated answer on relevance, groundedness, and clarity using the
configured LLM. Returns a normalized 0-1 score plus a short rationale. Parsing
is defensive so a malformed judge response never crashes the eval.
"""
import json
import logging
import re
from dataclasses import dataclass

try:
    from smra.utils.llm import call_llm
except (ModuleNotFoundError, ImportError):
    from utils.llm import call_llm

logger = logging.getLogger("smra.judge")

JUDGE_SYSTEM = """You are a strict evaluation judge for a financial research assistant.
Score the ANSWER to the QUESTION on three axes from 1 to 5:
- relevance: does it address the question?
- groundedness: are claims/numbers specific and plausible (not vague or evasive)?
- clarity: is it clear and well-structured?

Return ONLY a JSON object, no markdown:
{"relevance": 4, "groundedness": 4, "clarity": 5, "rationale": "one short sentence"}"""


@dataclass
class JudgeResult:
    score: float  # normalized 0-1
    relevance: int
    groundedness: int
    clarity: int
    rationale: str = ""


def _clamp(v, lo=1, hi=5) -> int:
    try:
        return max(lo, min(hi, int(round(float(v)))))
    except (TypeError, ValueError):
        return lo


def judge_answer(question: str, answer: str) -> JudgeResult:
    """Score an answer with the LLM judge; returns a low score on any failure."""
    if not answer or not answer.strip():
        return JudgeResult(score=0.0, relevance=1, groundedness=1, clarity=1, rationale="Empty answer")

    user = f"QUESTION:\n{question}\n\nANSWER:\n{answer}\n\nReturn the JSON scores."
    try:
        raw = call_llm(JUDGE_SYSTEM, user)
    except Exception:
        logger.exception("Judge LLM call failed")
        return JudgeResult(score=0.0, relevance=1, groundedness=1, clarity=1, rationale="Judge call failed")

    raw = (raw or "").strip().replace("```json", "").replace("```", "").strip()
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    try:
        parsed = json.loads(match.group() if match else raw)
    except Exception:
        logger.warning("Could not parse judge output: %s", raw[:120])
        return JudgeResult(score=0.0, relevance=1, groundedness=1, clarity=1, rationale="Unparseable judge output")

    relevance = _clamp(parsed.get("relevance", 1))
    groundedness = _clamp(parsed.get("groundedness", 1))
    clarity = _clamp(parsed.get("clarity", 1))
    score = round((relevance + groundedness + clarity) / 15.0, 3)  # normalize 3..15 -> 0..1
    return JudgeResult(
        score=score,
        relevance=relevance,
        groundedness=groundedness,
        clarity=clarity,
        rationale=str(parsed.get("rationale", ""))[:200],
    )
