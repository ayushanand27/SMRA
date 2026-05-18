import os
import json
import time
import logging
from pathlib import Path
try:
    from smra.utils.llm import call_llm
except Exception:
    logging.getLogger("smra.rag").exception("Package import for smra.utils.llm failed; falling back to local utils.llm")
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


RAG_SYSTEM = """You are a financial analyst. Answer using ONLY the context provided.
If context is insufficient, say exactly: "I couldn't find that in the available filings."
Always cite which document and page you found the answer in (e.g. [file.pdf p3])."""

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

        # 2) If Pinecone disabled, fallback to local store
        if _env_bool("PINECONE_DISABLED", False):
            import pickle

            store = _SMRA_ROOT / "data" / "rag_local_store.pkl"
            if not store.exists():
                logger.exception("Local RAG store not found at %s", store)
                return {"ok": False, "error": {"msg": "No local RAG store found. Run ingestion.", "type": "io"}, "fallback": True}

            with open(store, "rb") as f:
                payload = pickle.load(f)
            texts = payload.get("texts", [])
            metadatas = payload.get("metadatas", [])
            vectors = payload.get("vectors", [])

            # compute query vector
            try:
                qv = embeddings.embed_query(rewritten)
            except Exception:
                try:
                    qv = embeddings.embed_documents([rewritten])[0]
                except Exception as e2:
                    logger.exception("Failed to compute local store query embedding: %s", e2)
                    raise

            # compute cosine scores
            try:
                import numpy as np

                mat = np.asarray(vectors, dtype=np.float32)
                q = np.asarray(qv, dtype=np.float32)
                denom = (np.linalg.norm(mat, axis=1) * (np.linalg.norm(q) + 1e-10)) + 1e-10
                scores = (mat @ q) / denom
                idx = list(scores.argsort()[-top_k:][::-1])
                rows = [(texts[i], metadatas[i], float(scores[i])) for i in idx]
            except Exception:
                # fallback simple dot
                rows = []
                import math

                def dot(a, b):
                    return sum(x * y for x, y in zip(a, b))

                qn = math.sqrt(dot(qv, qv)) or 1.0
                for i, v in enumerate(vectors):
                    vn = math.sqrt(dot(v, v)) or 1.0
                    sc = dot(v, qv) / (vn * qn)
                    rows.append((texts[i], metadatas[i], float(sc)))
                rows.sort(key=lambda x: x[2], reverse=True)
                rows = rows[:top_k]

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
            answer = call_llm(RAG_SYSTEM, f"Context:\n{context}\n\nQuestion: {user_question}")
            return {"ok": True, "answer": answer, "data": rows, "meta": {"sources": sources, "scores": scores}}

        # 3) Use Pinecone
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

        if not rows:
            logger.info("No relevant content found in Pinecone index for query: %s", rewritten)
            return {"ok": False, "error": {"msg": "No relevant content found in the filings.", "type": "exec"}, "fallback": True}

        # Determine best score and handle web fallback
        best_score = max(r[2] for r in rows)
        if best_score < 0.5:
            logger.info("Best Pinecone score below threshold: %s", best_score)
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
        answer = call_llm(RAG_SYSTEM, f"Context:\n{context}\n\nQuestion: {user_question}")
        return {"ok": True, "answer": answer, "data": rows, "meta": {"sources": sources, "scores": scores}}

    except Exception as e:
        logger.exception("RAG error: %s", e)
        return {"ok": False, "error": {"msg": f"RAG error: {str(e)}", "type": "exec"}, "fallback": True}
