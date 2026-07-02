"""Faithfulness / grounding checks for RAG answers.

Financial answers must be traceable to source context. This module provides a
deterministic, dependency-free grounding signal: it verifies that the numeric
figures an answer asserts actually appear in the retrieved context. If an answer
introduces numbers not present in the sources, it is flagged as ungrounded so the
caller can abstain or append a caveat rather than present a possible hallucination.
"""
import re
from dataclasses import dataclass, field
from typing import List

_NUMBER_RE = re.compile(r"\$?\s*\d[\d,]*(?:\.\d+)?")


def _normalize_numbers(text: str) -> set[str]:
    numbers = set()
    for match in _NUMBER_RE.finditer(text or ""):
        raw = match.group(0)
        cleaned = re.sub(r"[^\d.]", "", raw)
        if cleaned and cleaned not in {".", ""}:
            cleaned = cleaned.rstrip(".")
            if cleaned:
                numbers.add(cleaned)
    return numbers


@dataclass
class FaithfulnessResult:
    grounded: bool
    score: float
    unsupported_numbers: List[str] = field(default_factory=list)


def check_numeric_grounding(answer: str, context: str, min_ratio: float = 0.6) -> FaithfulnessResult:
    """Check whether numbers in the answer are supported by the context.

    Returns grounded=True when no numbers are claimed, or when at least
    `min_ratio` of the claimed numbers appear in the context.
    """
    answer_numbers = _normalize_numbers(answer)
    if not answer_numbers:
        return FaithfulnessResult(grounded=True, score=1.0)

    context_numbers = _normalize_numbers(context)
    supported = {n for n in answer_numbers if n in context_numbers}
    unsupported = sorted(answer_numbers - supported)
    score = len(supported) / len(answer_numbers) if answer_numbers else 1.0

    return FaithfulnessResult(
        grounded=score >= min_ratio,
        score=round(score, 3),
        unsupported_numbers=unsupported,
    )


def has_citation(answer: str) -> bool:
    """Heuristic: does the answer reference a source/page?"""
    return bool(re.search(r"\[source|\bp\.?\s?\d+|\bpage\s+\d+|\.pdf", answer or "", re.IGNORECASE))
