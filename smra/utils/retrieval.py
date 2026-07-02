"""Hybrid retrieval and reranking utilities.

Combines dense vector similarity with sparse BM25 keyword matching (important for
regulatory/financial terminology), then optionally reranks with a cross-encoder.
All heavy components degrade gracefully when their libraries are unavailable so
the app keeps working offline.

Rows are represented as tuples: (text, metadata_dict, score).
"""
import logging
import re
from typing import List, Tuple

logger = logging.getLogger("smra.retrieval")

Row = Tuple[str, dict, float]

_cross_encoder = None
_cross_encoder_failed = False

_TOKEN_RE = re.compile(r"[A-Za-z0-9$%.,]+")


def _tokenize(text: str) -> List[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def _minmax_normalize(scores: List[float]) -> List[float]:
    if not scores:
        return []
    lo, hi = min(scores), max(scores)
    if hi - lo < 1e-9:
        return [0.5 for _ in scores]
    return [(s - lo) / (hi - lo) for s in scores]


def bm25_scores(query: str, corpus_texts: List[str]) -> List[float]:
    """Return BM25 relevance scores for each corpus text (0.0 if unavailable)."""
    if not corpus_texts:
        return []
    try:
        from rank_bm25 import BM25Okapi
    except Exception:
        logger.debug("rank_bm25 not installed; skipping sparse scoring")
        return [0.0] * len(corpus_texts)

    tokenized = [_tokenize(t) for t in corpus_texts]
    if not any(tokenized):
        return [0.0] * len(corpus_texts)
    bm25 = BM25Okapi(tokenized)
    return list(bm25.get_scores(_tokenize(query)))


def fuse_hybrid(
    query: str,
    dense_rows: List[Row],
    alpha: float = 0.5,
) -> List[Row]:
    """Fuse dense (vector) rows with BM25 sparse scores.

    alpha weights dense vs sparse: final = alpha*dense + (1-alpha)*sparse.
    Returns rows re-sorted by fused score (fused score stored in position 2).
    """
    if not dense_rows:
        return []

    texts = [r[0] for r in dense_rows]
    dense = _minmax_normalize([r[2] for r in dense_rows])
    sparse = _minmax_normalize(bm25_scores(query, texts))

    fused: List[Row] = []
    for i, (text, meta, _) in enumerate(dense_rows):
        s_sparse = sparse[i] if i < len(sparse) else 0.0
        score = alpha * dense[i] + (1 - alpha) * s_sparse
        fused.append((text, meta, float(score)))

    fused.sort(key=lambda r: r[2], reverse=True)
    return fused


def _get_cross_encoder(model_name: str = "cross-encoder/ms-marco-MiniLM-L-6-v2"):
    global _cross_encoder, _cross_encoder_failed
    if _cross_encoder is not None or _cross_encoder_failed:
        return _cross_encoder
    try:
        from sentence_transformers import CrossEncoder

        _cross_encoder = CrossEncoder(model_name, max_length=512)
    except Exception as exc:
        logger.info("Cross-encoder unavailable (%s); skipping rerank", type(exc).__name__)
        _cross_encoder_failed = True
    return _cross_encoder


def rerank(query: str, rows: List[Row], top_k: int, enabled: bool = True) -> List[Row]:
    """Rerank rows with a cross-encoder when available; otherwise pass through."""
    if not rows:
        return []
    if not enabled:
        return rows[:top_k]

    model = _get_cross_encoder()
    if model is None:
        return rows[:top_k]

    try:
        pairs = [(query, r[0]) for r in rows]
        scores = model.predict(pairs)
        reranked = [(rows[i][0], rows[i][1], float(scores[i])) for i in range(len(rows))]
        reranked.sort(key=lambda r: r[2], reverse=True)
        return reranked[:top_k]
    except Exception:
        logger.exception("Cross-encoder rerank failed; returning fused order")
        return rows[:top_k]


def hybrid_retrieve(
    query: str,
    dense_rows: List[Row],
    top_k: int,
    alpha: float = 0.5,
    use_rerank: bool = True,
) -> List[Row]:
    """Full hybrid pipeline: fuse dense+sparse, then optional cross-encoder rerank."""
    fused = fuse_hybrid(query, dense_rows, alpha=alpha)
    candidates = fused[: max(top_k * 3, top_k)]
    return rerank(query, candidates, top_k=top_k, enabled=use_rerank)
