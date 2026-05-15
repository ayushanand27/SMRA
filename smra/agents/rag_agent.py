import os
import hashlib
from pathlib import Path
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
    # Don't hard-fail if python-dotenv isn't installed in some environments.
    _SMRA_ROOT = Path(__file__).resolve().parents[1]

RAG_SYSTEM = """You are a financial analyst. Answer using ONLY the context provided.
If context is insufficient, say exactly: "I couldn't find that in the available filings."
Always cite which document/section you found the answer in."""

# Global embeddings cache to avoid repeated initialization
_embeddings_cache = None


def _get_embeddings(use_cache=True):
    """Load HuggingFace embeddings with timeout protection and caching."""
    global _embeddings_cache
    
    if use_cache and _embeddings_cache is not None:
        return _embeddings_cache
    
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
        # Set environment flags to speed up model loading
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
        print(f"[RAG] Failed to load HuggingFace embeddings: {e}")
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


def _get_pinecone_api_key() -> str:
    key = os.getenv("PINECONE_API_KEY") or os.getenv("PINECONE_KEY")
    if not key:
        raise RuntimeError(
            "Missing Pinecone API key. Set PINECONE_API_KEY in smra/.env (or PINECONE_KEY)."
        )
    return key


def _get_pinecone_index_name() -> str:
    # Support a few common env var names.
    return (
        os.getenv("PINECONE_INDEX")
        or os.getenv("PINECONE_INDEX_NAME")
        or os.getenv("PINECONE_INDEX_NAME")
        or "smra-index"
    )


def _get_pinecone_namespace(index=None) -> str:
    # Explicit env var wins.
    ns = os.getenv("PINECONE_NAMESPACE")
    if ns is not None:
        return ns

    # Otherwise: if index already has namespaces, pick the first.
    if index is not None:
        try:
            stats = index.describe_index_stats()
            namespaces = getattr(stats, "namespaces", None) or {}
            if isinstance(namespaces, dict) and namespaces:
                return list(namespaces.keys())[0]
        except Exception:
            pass
    return ""




def _get_pinecone_index():
    from pinecone import Pinecone
    pc = Pinecone(api_key=_get_pinecone_api_key())
    index_name = _get_pinecone_index_name()

    # List indexes to confirm it exists
    if _env_bool("PINECONE_VALIDATE_INDEX", True):
        available = [i.name for i in pc.list_indexes()]
        print(f"[Pinecone] Available indexes: {available}")
        if index_name not in available:
            raise ValueError(f"Index '{index_name}' not found! Available: {available}")

    index = pc.Index(index_name)
    try:
        stats = index.describe_index_stats()
        print(f"[Pinecone] Index stats: {stats}")
    except Exception as e:
        print(f"[Pinecone] Could not fetch index stats yet: {e}")
    return index, index_name


def _clear_pinecone_index(index) -> None:
    """Clear all vectors in the index (all namespaces if present)."""
    namespaces: list[str]
    try:
        stats = index.describe_index_stats()
        ns_map = getattr(stats, "namespaces", None) or {}
        namespaces = list(ns_map.keys()) if isinstance(ns_map, dict) else []
    except Exception:
        namespaces = []

    # If index has no namespaces yet, Pinecone uses the empty-string namespace.
    if not namespaces:
        namespaces = [""]

    for ns in namespaces:
        try:
            index.delete(delete_all=True, namespace=ns)
        except TypeError:
            # Very old clients
            if ns == "":
                index.delete(delete_all=True)
            else:
                raise

    print(f"[Pinecone] Cleared vectors in namespaces: {namespaces}")


def _extract_pages_text_pdfplumber(pdf_path: Path, max_pages: int | None) -> list[tuple[int, str]]:
    """Best-effort text extraction using pdfplumber (no OCR)."""
    try:
        import pdfplumber
    except Exception as e:
        raise RuntimeError("pdfplumber is required for PDF text extraction") from e

    pages: list[tuple[int, str]] = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for i, page in enumerate(pdf.pages):
            if max_pages is not None and i >= max_pages:
                break
            text = page.extract_text() or ""
            pages.append((i + 1, text))
    return pages


def _extract_pages_text_ocr(pdf_path: Path, max_pages: int) -> list[tuple[int, str]]:
    """OCR-based extraction for scanned PDFs."""
    try:
        from pdf2image import convert_from_path
    except Exception as e:
        raise RuntimeError("pdf2image is required for OCR fallback") from e

    try:
        import pytesseract
    except Exception as e:
        raise RuntimeError("pytesseract is required for OCR fallback") from e

    tesseract_cmd = os.getenv("TESSERACT_CMD")
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    poppler_path = os.getenv("POPPLER_PATH") or None
    dpi = _env_int("OCR_DPI", 200)
    lang = os.getenv("OCR_LANG")

    kwargs = {"dpi": dpi}
    if poppler_path:
        kwargs["poppler_path"] = poppler_path
    if max_pages and max_pages > 0:
        kwargs["first_page"] = 1
        kwargs["last_page"] = max_pages

    images = convert_from_path(str(pdf_path), **kwargs)
    out: list[tuple[int, str]] = []
    for page_num, img in enumerate(images, start=1):
        if lang:
            text = pytesseract.image_to_string(img, lang=lang) or ""
        else:
            text = pytesseract.image_to_string(img) or ""
        out.append((page_num, text))
    return out


def _pages_to_documents(source_name: str, pages: list[tuple[int, str]]):
    from langchain_core.documents import Document

    docs = []
    for page_num, text in pages:
        if not (text or "").strip():
            continue
        docs.append(Document(page_content=text, metadata={"source": source_name, "page": page_num}))
    return docs


def _build_chunks_from_pdf(pdf_path: Path):
    from langchain.text_splitter import RecursiveCharacterTextSplitter

    text_max_pages = _env_int("RAG_TEXT_MAX_PAGES", 0)
    text_max_pages = None if text_max_pages <= 0 else text_max_pages

    ocr_max_pages = _env_int("OCR_MAX_PAGES", 10)
    ocr_min_chars = _env_int("OCR_MIN_TEXT_CHARS", 200)
    force_ocr = _env_bool("OCR_FORCE", False)

    pages = _extract_pages_text_pdfplumber(pdf_path, max_pages=text_max_pages)
    extracted_chars = sum(len((t or "").strip()) for _, t in pages)

    if force_ocr or extracted_chars < ocr_min_chars:
        try:
            print(f"[RAG][OCR] '{pdf_path.name}' looks scanned/empty (chars={extracted_chars}); running OCR...")
            pages = _extract_pages_text_ocr(pdf_path, max_pages=ocr_max_pages)
        except Exception as e:
            print(f"[RAG][OCR] OCR failed for {pdf_path.name}: {e}")

    docs = _pages_to_documents(pdf_path.name, pages)
    splitter = RecursiveCharacterTextSplitter(chunk_size=800, chunk_overlap=150)
    return splitter.split_documents(docs)


def _local_store_path() -> Path:
    default_path = _SMRA_ROOT / "data" / "rag_local_store.pkl"
    return Path(os.getenv("RAG_LOCAL_STORE_PATH") or default_path)


def _write_local_store(chunks, vectors) -> None:
    import pickle

    store_path = _local_store_path()
    store_path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "embedding_model": "sentence-transformers/all-MiniLM-L6-v2",
        "dim": len(vectors[0]) if vectors else 0,
        "texts": [c.page_content for c in chunks],
        "metadatas": [dict(c.metadata) for c in chunks],
        "vectors": vectors,
    }

    with open(store_path, "wb") as f:
        pickle.dump(payload, f)
    print(f"[RAG] Wrote local fallback store: {store_path} ({len(vectors)} vectors)")


def _local_similarity_search(query: str, k: int):
    import pickle

    store_path = _local_store_path()
    if not store_path.exists():
        return []

    with open(store_path, "rb") as f:
        payload = pickle.load(f)

    vectors = payload.get("vectors") or []
    texts = payload.get("texts") or []
    metadatas = payload.get("metadatas") or []
    if not vectors or not texts or len(vectors) != len(texts):
        return []

    embeddings = _get_embeddings()
    qv = embeddings.embed_query(query)

    # Prefer numpy for speed if available.
    try:
        import numpy as np

        mat = np.asarray(vectors, dtype=np.float32)
        q = np.asarray(qv, dtype=np.float32)
        denom = (np.linalg.norm(mat, axis=1) * (np.linalg.norm(q) + 1e-10)) + 1e-10
        scores = (mat @ q) / denom
        top_idx = np.argsort(scores)[-k:][::-1]
        return [(texts[i], metadatas[i]) for i in top_idx]
    except Exception:
        # Pure-Python fallback
        import math

        def dot(a, b):
            return sum((x * y) for x, y in zip(a, b))

        qn = math.sqrt(dot(qv, qv)) or 1.0
        scored = []
        for i, v in enumerate(vectors):
            vn = math.sqrt(dot(v, v)) or 1.0
            scored.append((dot(v, qv) / (vn * qn), i))
        scored.sort(reverse=True)
        return [(texts[i], metadatas[i]) for _, i in scored[:k]]


def ingest_pdfs(pdf_folder: str):
    embeddings = _get_embeddings()

    all_chunks = []
    pdf_files = list(Path(pdf_folder).glob("*.pdf"))

    if not pdf_files:
        print("[RAG] No PDFs found in folder!")
        return

    for pdf_path in pdf_files:
        print(f"[RAG] Processing {pdf_path.name}...")
        try:
            chunks = _build_chunks_from_pdf(pdf_path)
            for c in chunks:
                c.metadata.setdefault("source", pdf_path.name)
            all_chunks.extend(chunks)
            print(f"[RAG] → {len(chunks)} chunks from {pdf_path.name}")
        except Exception as e:
            print(f"[RAG] Failed to process {pdf_path.name}: {e}")

    if not all_chunks:
        print("[RAG] No text extracted from PDFs (even after OCR fallback)!")
        return

    print(f"[RAG] Embedding {len(all_chunks)} chunks...")
    texts = [c.page_content for c in all_chunks]
    vectors = embeddings.embed_documents(texts)

    # Optional: local fallback store
    if _env_bool("RAG_WRITE_LOCAL_STORE", True):
        try:
            _write_local_store(all_chunks, vectors)
        except Exception as e:
            print(f"[RAG] Failed to write local store (continuing): {e}")

    if _env_bool("PINECONE_DISABLED", False):
        print("[RAG] PINECONE_DISABLED=1 set; skipping Pinecone upload.")
        return

    print(f"[RAG] Uploading {len(all_chunks)} vectors into Pinecone...")

    index, index_name = _get_pinecone_index()
    namespace = _get_pinecone_namespace(index)
    print(f"[RAG] Using index='{index_name}', namespace='{namespace}'")

    if _env_bool("PINECONE_CLEAR_BEFORE_INGEST", True):
        try:
            _clear_pinecone_index(index)
        except Exception as e:
            print(f"[Pinecone] Could not clear index (continuing): {e}")

    upsert_batch = _env_int("PINECONE_UPSERT_BATCH", 100)
    vectors_to_upsert = []
    for i, (doc, vec) in enumerate(zip(all_chunks, vectors)):
        meta = dict(doc.metadata)
        meta["text"] = doc.page_content
        meta["chunk"] = i
        source = str(meta.get("source", "unknown"))
        page = str(meta.get("page", ""))
        vid = hashlib.sha1(f"{source}|{page}|{doc.page_content}".encode("utf-8", "ignore")).hexdigest()
        # Format as dict matching Pinecone SDK: {"id": ..., "values": ..., "metadata": ...}
        vectors_to_upsert.append({"id": vid, "values": vec, "metadata": meta})

    for start in range(0, len(vectors_to_upsert), upsert_batch):
        batch = vectors_to_upsert[start:start + upsert_batch]
        index.upsert(vectors=batch, namespace=namespace)
        print(f"[RAG] Uploaded {min(start + upsert_batch, len(vectors_to_upsert))}/{len(vectors_to_upsert)}")

    try:
        stats = index.describe_index_stats()
        print(f"[RAG] Done! Pinecone now has {stats.total_vector_count} vectors.")
        print(f"[RAG] Namespaces: {getattr(stats, 'namespaces', None)}")
    except Exception as e:
        print(f"[RAG] Uploaded, but couldn't read stats: {e}")


def run_rag_agent(user_question: str) -> dict:
    try:
        embeddings = _get_embeddings()
        top_k = _env_int("RAG_TOP_K", 4)

        if _env_bool("PINECONE_DISABLED", False):
            results = _local_similarity_search(user_question, k=top_k)
            if not results:
                return {
                    "answer": "No documents have been ingested locally yet. Run ingest_pdfs() first.",
                    "sources": [],
                }
            context = "\n\n---\n\n".join(
                [
                    f"[{(m or {}).get('source', 'Unknown')} p{(m or {}).get('page', '?')}]\n{t}"
                    for t, m in results
                ]
            )
            sources = sorted({(m or {}).get("source", "Unknown") for _, m in results})
            answer = call_llm(RAG_SYSTEM, f"Context:\n{context}\n\nQuestion: {user_question}")
            return {"answer": answer, "sources": sources}

        pinecone_error = None
        try:
            index, index_name = _get_pinecone_index()
            namespace = _get_pinecone_namespace(index)
            print(f"[RAG] Querying index='{index_name}', namespace='{namespace}'")

            qv = embeddings.embed_query(user_question)
            res = index.query(
                vector=qv,
                top_k=top_k,
                namespace=namespace,
                include_metadata=True,
            )

            matches = getattr(res, "matches", None) or []
            if not matches:
                return {"answer": "No relevant content found in the filings.", "sources": []}

            rows = []
            for m in matches:
                meta = getattr(m, "metadata", None) or {}
                text = meta.get("text") or ""
                if not text:
                    continue
                rows.append((text, meta))

            if not rows:
                return {"answer": "No relevant content found in the filings.", "sources": []}

            context = "\n\n---\n\n".join(
                [
                    f"[{(m or {}).get('source', 'Unknown')} p{(m or {}).get('page', '?')}]\n{t}"
                    for t, m in rows
                ]
            )
            sources = sorted({(m or {}).get("source", "Unknown") for _, m in rows})
            answer = call_llm(RAG_SYSTEM, f"Context:\n{context}\n\nQuestion: {user_question}")
            return {"answer": answer, "sources": sources}
        except Exception as e:
            pinecone_error = str(e)

        # Fallback to local store if Pinecone is unreachable.
        results = _local_similarity_search(user_question, k=top_k)
        if results:
            context = "\n\n---\n\n".join(
                [
                    f"[{(m or {}).get('source', 'Unknown')} p{(m or {}).get('page', '?')}]\n{t}"
                    for t, m in results
                ]
            )
            sources = sorted({(m or {}).get("source", "Unknown") for _, m in results})
            answer = call_llm(RAG_SYSTEM, f"Context:\n{context}\n\nQuestion: {user_question}")
            return {"answer": answer, "sources": sources}

        return {
            "answer": f"RAG error: {pinecone_error}",
            "sources": [],
        }

    except Exception as e:
        print(f"[RAG] Error: {e}")
        return {"answer": f"RAG error: {str(e)}", "sources": []}