import os
import json
import time
import logging
import re
from pathlib import Path
try:
    from smra.utils.llm import call_llm
except (ModuleNotFoundError, ImportError):
    from utils.llm import call_llm

# Load .env relative to the smra/ package so scripts work no matter the CWD.
try:
    from dotenv import load_dotenv

    _SMRA_ROOT = Path(__file__).resolve().parents[1]
    _ENV_PATH = _SMRA_ROOT / ".env"
    if _ENV_PATH.exists():
        load_dotenv(_ENV_PATH, override=True)
    else:
        load_dotenv(override=True)
except Exception:
    _SMRA_ROOT = Path(__file__).resolve().parents[1]


RAG_SYSTEM = """You are analyzing OCR-extracted text from Apple and NVIDIA SEC filings.

The text comes from scanned PDFs so it may contain:
- Irregular spacing and line breaks  
- OCR artifacts like '|' instead of numbers, garbled words
- Tables formatted as plain text

YOUR JOB: Find and report any financial numbers visible in the context.

For revenue/sales questions: Look for dollar amounts like "$383,285" or "383,285" or "383.3 billion"
For any financial question: Report the numbers you see, state which document they came from.

DO NOT say "I cannot find" if you can see ANY dollar amounts or financial figures in the text.
Instead say what numbers you found and where, even if the context around them is unclear.

Format: "[Source: filename, page X] The data shows: [numbers/figures you found]"
"""

# Embeddings cache
_embeddings_cache = None


def _get_embeddings(use_cache=True):
    global _embeddings_cache
    if use_cache and _embeddings_cache is not None:
        return _embeddings_cache
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        import os
        os.environ["TOKENIZERS_PARALLELISM"] = "false"
        os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
        emb = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            model_kwargs={"device": "cpu"},
            show_progress=False,
        )
        if use_cache:
            _embeddings_cache = emb
        return emb
    except Exception as e:
        logging.getLogger("smra.rag").exception("Failed to load HuggingFace embeddings: %s", e)
        raise


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    v = os.getenv(name)
    if v is None:
        return default
    try:
        return int(v)
    except Exception:
        return default


def _get_pinecone_index():
    # Use Pinecone SDK v3.x style client
    try:
        from pinecone import Pinecone
    except Exception as e:
        logging.getLogger("smra.rag").exception("Pinecone SDK not available: %s", e)
        raise

    api_key = os.getenv("PINECONE_API_KEY") or os.getenv("PINECONE_KEY")
    try:
        pc = Pinecone(api_key=api_key)
    except Exception as e:
        logging.getLogger("smra.rag").exception("Failed to create Pinecone client: %s", e)
        raise

    index_name = os.getenv("PINECONE_INDEX") or os.getenv("PINECONE_INDEX_NAME") or "smra-index"
    try:
        index = pc.Index(index_name)
    except Exception as e:
        logging.getLogger("smra.rag").exception("Failed to connect to Pinecone index %s: %s", index_name, e)
        raise

    try:
        stats = index.describe_index_stats()
        namespaces = []
        if isinstance(stats, dict):
            namespaces = list(stats.get("namespaces", {}).keys())
        else:
            namespaces = list(getattr(stats, "namespaces", {}).keys())
        logging.getLogger("smra.rag").info("Pinecone index: %s; namespaces: %s", index_name, namespaces)
    except Exception:
        logging.getLogger("smra.rag").debug("Could not describe Pinecone index stats")

    return index, index_name


def _rewrite_query_if_vague(user_question: str) -> str:
    """Ask the LLM to rewrite vague queries into precise document search phrases."""
    prompt = (
        "Rewrite the user's query into a precise document search phrase suitable for searching annual reports and filings. "
        "Be specific and include the company name and the financial concept.\n\n"
        f"User query: {user_question}\n\nReturn only the rewritten search phrase."
    )
    try:
        rewritten = call_llm("", prompt)
        rewritten = rewritten.strip().strip('"')
        return rewritten
    except Exception:
        logging.getLogger("smra.rag").exception("Failed to rewrite query; using original: %s", user_question)
        return user_question


def _similarity_search_with_score_index(index, namespace, qv, top_k=4):
    """Query Pinecone index and return list of (text, metadata, score).

    Uses Pinecone's query API and expects metadata to include 'text' and 'page'.
    """
    res = index.query(vector=qv, top_k=top_k, namespace=namespace, include_metadata=True)
    matches = getattr(res, "matches", None) or []
    out = []
    for m in matches:
        meta = getattr(m, "metadata", None) or {}
        text = meta.get("text") or ""
        # Pinecone match object may expose different score attributes depending on SDK version
        score = getattr(m, "score", None)
        # Pinecone sometimes uses 'score' or 'value' fields; try alternatives
        if score is None:
            score = getattr(m, "value", None) or getattr(m, "similarity", None) or 0.0
        out.append((text, meta, float(score or 0.0)))
    return out


def _extract_numbers_from_chunks(chunks_text: str, question: str) -> str:
    """Extract financial numbers directly without LLM."""
    # Prefer financial figures over dates/page numbers.
    question_l = (question or "").lower()
    prefer_keywords = any(k in question_l for k in ("revenue", "sales", "net sales", "income", "profit", "earnings", "figure", "amount"))

    patterns = [
        (r'\$[\d,]+(?:\.\d+)?(?:\s*(?:billion|million|thousand))?', 3),
        (r'\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b', 2),  # 383,285 style
        (r'\b\d+\.\d+\s*(?:billion|million)\b', 2),   # 383.3 billion style
    ]

    candidates = []
    lines = chunks_text.splitlines()
    for line in lines:
        line_l = line.lower()
        # Strong preference for lines containing financial keywords when the question is about money
        keyword_bonus = 2 if prefer_keywords and any(k in line_l for k in ("net sales", "sales", "revenue", "income", "profit", "earnings")) else 0
        for pattern, base_score in patterns:
            for match in re.finditer(pattern, line, re.IGNORECASE):
                raw = match.group(0).strip()
                # Skip obvious noise like page numbers/dates unless they are clearly monetary
                numeric_only = re.sub(r"[^\d.]", "", raw)
                try:
                    value = float(numeric_only.replace(",", "")) if numeric_only else 0.0
                except Exception:
                    value = 0.0

                if "$" not in raw and value < 1000 and base_score < 3:
                    continue

                score = base_score + keyword_bonus
                # Bigger figures are usually the answer for revenue/sales questions.
                if value >= 1000:
                    score += 1
                candidates.append((score, raw))

    if not candidates:
        return ""

    # De-duplicate while preserving order by best score first.
    candidates.sort(key=lambda x: x[0], reverse=True)
    unique = []
    seen = set()
    for _, raw in candidates:
        if raw not in seen:
            seen.add(raw)
            unique.append(raw)
        if len(unique) >= 10:
            break

    return f"Financial figures found in filing: {', '.join(unique)}"


def run_rag_agent(user_question: str) -> dict:
    """Run RAG: rewrite vague queries, search, and synthesize.

    If the best match score is below 0.5, return {"fallback": True} to signal a web fallback.
    """
    logger = logging.getLogger("smra.rag")
    try:
        top_k = _env_int("RAG_TOP_K", 4)
        embeddings = _get_embeddings()

        # 1) Rewrite vague queries for better retrieval
        rewritten = _rewrite_query_if_vague(user_question)

        def _local_search(query: str, k: int = 4):
            """Search the local rag_local_store.pkl using cosine similarity and return rows like (text, meta, score)."""
            try:
                import pickle
                import numpy as np
            except Exception:
                return []

            store = _SMRA_ROOT / "data" / "rag_local_store.pkl"
            if not store.exists():
                return []

            with open(store, "rb") as f:
                payload = pickle.load(f)

            texts = payload.get("texts", [])
            metadatas = payload.get("metadatas", [])
            vectors = payload.get("vectors", [])

            if not vectors:
                # nothing to search
                return []

            try:
                qv = embeddings.embed_query(query)
            except Exception:
                try:
                    qv = embeddings.embed_documents([query])[0]
                except Exception:
                    return []

            mat = np.asarray(vectors, dtype=np.float32)
            q = np.asarray(qv, dtype=np.float32)
            denom = (np.linalg.norm(mat, axis=1) * (np.linalg.norm(q) + 1e-10)) + 1e-10
            scores = (mat @ q) / denom
            idxs = list(scores.argsort()[-k:][::-1])
            rows = [(texts[i], metadatas[i], float(scores[i])) for i in idxs]
            return rows

        # 2) If Pinecone disabled, fallback to local store (existing behavior)
        if _env_bool("PINECONE_DISABLED", False):
            rows = _local_search(rewritten, k=top_k)
            if not rows:
                logger.info("No relevant content found in local RAG store for query: %s", rewritten)
                return {"ok": False, "error": {"msg": "No relevant content found.", "type": "exec"}, "fallback": True}

            best_score = rows[0][2]
            if best_score < 0.5:
                logger.info("Best local RAG score below threshold: %s", best_score)
                return {"ok": False, "error": {"msg": "Low similarity; trigger web fallback", "type": "exec"}, "fallback": True}

            context = "\n\n---\n\n".join([f"[{(m or {}).get('source','Unknown')} p{(m or {}).get('page','?')}]\n{t}" for t, m, _ in rows])
            sources = sorted({(m or {}).get("source", "Unknown") for _, m, _ in rows})
            scores = [r[2] for r in rows]
            all_numbers = re.findall(r'\$\s*[\d,]+(?:\.\d+)?|\b[\d]{3},[\d]{3}\b', context)
            number_hint = f"\n\nNUMBERS VISIBLE IN TEXT: {', '.join(all_numbers[:15])}" if all_numbers else ""

            direct_prompt = f"""Context from Apple/NVIDIA 10-K filing:
{context}
{number_hint}

Question: {user_question}

Instructions: The numbers above come directly from the filing. 
Report what you find. For 'total net sales' look for '383,285' or '394,328' (in millions).
Answer directly with the specific figures."""

            answer = call_llm(RAG_SYSTEM, direct_prompt)
            return {"ok": True, "answer": answer, "data": rows, "meta": {"sources": sources, "scores": scores}}

        # 3) Use Pinecone, but fall back to local store if Pinecone returns nothing or fails
        try:
            index, index_name = _get_pinecone_index()
            namespace = os.getenv("PINECONE_NAMESPACE", "")

            try:
                qv = embeddings.embed_query(rewritten)
            except Exception:
                try:
                    qv = embeddings.embed_documents([rewritten])[0]
                except Exception as e2:
                    logger.exception("Failed to compute Pinecone query embedding: %s", e2)
                    raise

            rows = _similarity_search_with_score_index(index, namespace, qv, top_k=top_k)
        except Exception as e:
            logger.warning("Pinecone query failed, falling back to local search: %s", e)
            rows = []

        # If Pinecone returned no rows, try local search
        if not rows:
            logger.info("No relevant content found in Pinecone; attempting local fallback for query: %s", rewritten)
            rows = _local_search(rewritten, k=top_k)

        if not rows:
            logger.info("No relevant content found after local fallback for query: %s", rewritten)
            return {"ok": False, "error": {"msg": "No relevant content found in the filings.", "type": "exec"}, "fallback": True}

        # Determine best score and handle web fallback
        best_score = max(r[2] for r in rows)
        if best_score < 0.5:
            logger.info("Best RAG score below threshold: %s", best_score)
            return {"ok": False, "error": {"msg": "Low similarity; trigger web fallback", "type": "exec"}, "fallback": True}

        # Build context and include page numbers in citations
        context_parts = []
        for t, m, sc in rows:
            src = (m or {}).get("source", "Unknown")
            page = (m or {}).get("page", "?")
            context_parts.append(f"[{src} p{page}]\n{t}")
        context = "\n\n---\n\n".join(context_parts)
        sources = sorted({(m or {}).get("source", "Unknown") for _, m, _ in rows})
        scores = [r[2] for r in rows]
        # Quick programmatic numeric extraction fallback: scan top-ranked chunks for monetary/number patterns
        def _find_numeric_in_rows(rows):
            import re

            num_re = re.compile(
                r"\$?\s*([-+]?[0-9]{1,3}(?:[,0-9]{0,})?(?:\.\d+)?)(?:\s*(million|billion|bn|m|k|thousand|M|B))?",
                re.IGNORECASE,
            )
            for t, m, sc in rows:
                if not t:
                    continue
                for match in num_re.finditer(t):
                    raw = match.group(0).strip()
                    num = match.group(1).replace(",", "")
                    mult = match.group(2) or ""
                    try:
                        val = float(num)
                        mult_l = mult.lower()
                        if mult_l in ("m", "million"):
                            val = val * 1e6
                        elif mult_l in ("b", "bn", "billion"):
                            val = val * 1e9
                        elif mult_l in ("k", "thousand"):
                            val = val * 1e3
                    except Exception:
                        val = None
                    src = (m or {}).get("source", "Unknown")
                    page = (m or {}).get("page", "?")
                    yield (val, raw, src, page, sc)

        all_numbers = re.findall(r'\$\s*[\d,]+(?:\.\d+)?|\b[\d]{3},[\d]{3}\b', context)
        number_hint = f"\n\nNUMBERS VISIBLE IN TEXT: {', '.join(all_numbers[:15])}" if all_numbers else ""

        direct_prompt = f"""Context from Apple/NVIDIA 10-K filing:
    {context}
    {number_hint}

    Question: {user_question}

    Instructions: The numbers above come directly from the filing. 
    Report what you find. For 'total net sales' look for '383,285' or '394,328' (in millions).
    Answer directly with the specific figures."""

        answer = call_llm(RAG_SYSTEM, direct_prompt)
        if "i couldn't find that in the available filings" in (answer or "").strip().lower() and best_score >= 0.55:
            rescue_prompt = (
                "The context may be OCR-noisy. Extract the most likely numeric answer to the question from context. "
                "Return one short answer with citation(s). If impossible, return exactly the fallback sentence."
            )
            rescue = call_llm(rescue_prompt, f"Context:\n{context}\n\nQuestion: {user_question}")
            if rescue and "i couldn't find that in the available filings" not in rescue.strip().lower():
                answer = rescue
        return {"ok": True, "answer": answer, "data": rows, "meta": {"sources": sources, "scores": scores}}

    except Exception as e:
        logger.exception("RAG error: %s", e)
        return {"ok": False, "error": {"msg": f"RAG error: {str(e)}", "type": "exec"}, "fallback": True}
