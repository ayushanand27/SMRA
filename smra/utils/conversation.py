"""History-aware query contextualization for multi-turn conversations.

Both smra.api and smra.app treat every query independently today: a follow-up
like "what about last year?" is routed and answered with zero awareness of
what "it" refers to. This module resolves such follow-ups into standalone
questions using recent conversation turns, before routing/agent execution
runs — the same "condense question" pattern used by most conversational RAG
systems.

Deliberately stateless: the caller (API client or the Streamlit session) owns
and sends the history. Nothing is persisted server-side, so this adds no new
storage/session infrastructure and works the same for a single API replica
or many.
"""
import logging
from typing import TypedDict

try:
    from smra.utils.llm import call_llm
except (ModuleNotFoundError, ImportError):
    from utils.llm import call_llm

logger = logging.getLogger("smra.conversation")

# ~3 user/assistant exchanges. Bounds LLM token cost and latency; older turns
# are very rarely what a follow-up like "what about X" actually refers to.
MAX_HISTORY_TURNS = 6


class Turn(TypedDict):
    role: str
    content: str


_CONTEXTUALIZE_SYSTEM = """Given a chat history and the latest user question, decide whether the \
question depends on the conversation above (uses pronouns like "it"/"that", says "what about X", \
omits a subject already established earlier, etc).

- If it depends on prior turns, rewrite it into a standalone question that contains all the \
context needed to answer it without seeing the history. Preserve the original intent and \
specificity exactly; do not add information that wasn't implied by the conversation.
- If it is already standalone, return it completely unchanged.

Return ONLY the resulting question text. No explanation, no quotes, no markdown."""


def _clean_turns(history: list[Turn] | None) -> list[Turn]:
    if not history:
        return []
    cleaned = [
        t
        for t in history
        if isinstance(t, dict) and t.get("role") in {"user", "assistant"} and (t.get("content") or "").strip()
    ]
    return cleaned[-MAX_HISTORY_TURNS:]


def contextualize_query(history: list[Turn] | None, current_query: str) -> str:
    """Rewrite current_query into a standalone question using recent history.

    No-ops (returns current_query unchanged, no LLM call) when there's no
    usable history, so a first-turn query pays zero extra latency.
    Falls back to the original query if the rewrite call fails for any
    reason — a broken contextualization step should never block answering.
    """
    turns = _clean_turns(history)
    if not turns:
        return current_query

    transcript = "\n".join(f"{t['role']}: {t['content']}" for t in turns)
    user_prompt = f"Chat history:\n{transcript}\n\nLatest question: {current_query}"

    try:
        rewritten = call_llm(_CONTEXTUALIZE_SYSTEM, user_prompt, max_tokens=200, temperature=0.0)
    except Exception:
        logger.exception("Query contextualization failed; using original query unchanged")
        return current_query

    rewritten = (rewritten or "").strip().strip('"')
    return rewritten if rewritten else current_query
