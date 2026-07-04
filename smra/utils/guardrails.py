"""Input/output guardrails aligned with the OWASP Top 10 for LLM Applications.

Defense-in-depth, deterministic first layer:
- LLM01 Prompt Injection: reject known jailbreak/override patterns.
- Input hygiene: length limits, control/zero-width character stripping.
- LLM02 Insecure Output Handling: strip unsafe HTML/script from model output.

This is intentionally rule-based and dependency-free so it runs with zero
latency before any model call. It is a first layer, not a complete defense.
"""
import re
import unicodedata
from dataclasses import dataclass

try:
    from smra.utils.config import get_settings
except (ModuleNotFoundError, ImportError):
    from utils.config import get_settings

# Known prompt-injection / jailbreak signatures (LLM01).
# Patterns are intentionally typo-tolerant: `instr\w*` matches "instructions"
# and common misspellings (e.g. "instrcutions"), and "your"/"ur" are both
# accepted, since attackers rarely spell perfectly.
_YOUR = r"(?:your\s+|ur\s+)?"
_INJECTION_PATTERNS = [
    rf"ignore\s+(?:all\s+)?{_YOUR}(?:previous|prior|above|prev)\s+instr\w*",
    rf"disregard\s+(?:all\s+)?{_YOUR}(?:previous|prior|above)\s+(?:instr\w*|prompts?)",
    r"ignore\s+(?:all\s+)?(?:the\s+)?(?:previous|prior|above)\s+(?:instr\w*|prompts?|context|rules?)",
    r"forget\s+(?:everything|all)\s+(?:you|above)",
    r"you\s+are\s+now\s+(?:a|an|in)\s+",
    r"\bDAN\b\s+mode",
    r"developer\s+mode",
    r"system\s+prompt\s*[:=]",
    rf"reveal\s+{_YOUR}(?:system\s+)?(?:prompt|instr\w*)",
    rf"print\s+{_YOUR}(?:system\s+)?(?:prompt|instr\w*)",
    rf"show\s+(?:me\s+)?{_YOUR}(?:system\s+)?(?:prompt|instr\w*)",
    r"act\s+as\s+(?:if\s+you\s+are\s+)?(?:an?\s+)?(?:unrestricted|jailbroken)",
    r"do\s+anything\s+now",
]

# Dangerous SQL/DDL an untrusted query should never carry into our pipeline.
_SQL_ABUSE_PATTERNS = [
    r"\bDROP\s+TABLE\b",
    r"\bDELETE\s+FROM\b",
    r"\bTRUNCATE\b",
    r";\s*(?:DROP|DELETE|UPDATE|INSERT|ALTER)\b",
]

_INJECTION_RE = re.compile("|".join(_INJECTION_PATTERNS), re.IGNORECASE)
_SQL_ABUSE_RE = re.compile("|".join(_SQL_ABUSE_PATTERNS), re.IGNORECASE)
_ZERO_WIDTH_RE = re.compile(r"[\u200b-\u200f\u202a-\u202e\ufeff]")
_SCRIPT_RE = re.compile(r"<\s*script.*?>.*?<\s*/\s*script\s*>", re.IGNORECASE | re.DOTALL)
_HTML_TAG_RE = re.compile(r"<[^>]+>")


@dataclass
class GuardrailResult:
    ok: bool
    text: str
    reason: str = ""


def sanitize_input(text: str) -> str:
    """Normalize unicode, strip zero-width/control chars, collapse whitespace."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text)
    text = _ZERO_WIDTH_RE.sub("", text)
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or not unicodedata.category(ch).startswith("C"))
    return text.strip()


def check_input(text: str, max_chars: int | None = None) -> GuardrailResult:
    """Validate a user query before it reaches any LLM or SQL layer."""
    settings = get_settings()
    if not settings.guardrails_enabled:
        return GuardrailResult(ok=True, text=(text or "").strip())

    cleaned = sanitize_input(text)

    if not cleaned:
        return GuardrailResult(ok=False, text="", reason="Empty query after sanitization.")

    limit = max_chars if max_chars is not None else settings.max_input_chars
    if len(cleaned) > limit:
        return GuardrailResult(
            ok=False,
            text=cleaned[:limit],
            reason=f"Query exceeds the {limit}-character limit.",
        )

    if _INJECTION_RE.search(cleaned):
        return GuardrailResult(ok=False, text=cleaned, reason="Potential prompt-injection pattern detected.")

    if _SQL_ABUSE_RE.search(cleaned):
        return GuardrailResult(ok=False, text=cleaned, reason="Potential SQL abuse pattern detected.")

    return GuardrailResult(ok=True, text=cleaned)


def sanitize_output(text: str) -> str:
    """Strip script/HTML from model output before rendering (LLM02)."""
    if not text:
        return ""
    text = _SCRIPT_RE.sub("", text)
    text = _HTML_TAG_RE.sub("", text)
    return text.strip()
