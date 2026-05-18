import os
import sys
import pickle
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load .env from smra/ so variables like PINECONE_API_KEY are available
script_dir = Path(__file__).resolve().parent
smra_root = script_dir.parent
env_path = smra_root / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    load_dotenv(override=True)

sys.path.insert(0, str(smra_root))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("upload")


def upload_direct_vectors():
    """Upload vectors directly from rag_local_store.pkl to Pinecone using whichever client is available."""
    # ensure .env is loaded (best-effort): parse smra/.env if needed
    def _ensure_env_loaded():
        if os.getenv("PINECONE_API_KEY"):
            return
        envf = smra_root / ".env"
        if not envf.exists():
            return
        try:
            with open(envf, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip()
                    # remove surrounding quotes
                    if v.startswith('"') and v.endswith('"'):
                        v = v[1:-1]
                    if v.startswith("'") and v.endswith("'"):
                        v = v[1:-1]
                    os.environ.setdefault(k, v)
        except Exception:
            pass

    _ensure_env_loaded()

    store_path = Path("data") / "rag_local_store.pkl"
    if not store_path.exists():
        logger.error("rag_local_store.pkl not found! Run ingest_pdfs.py first.")
        return

    with open(store_path, "rb") as f:
        payload = pickle.load(f)

    texts = payload.get("texts", [])
    metadatas = payload.get("metadatas", [{}] * len(texts))
    vectors = payload.get("vectors", [])

    if not vectors:
        logger.error("No vectors found in local store; aborting upload")
        return

    index_name = os.getenv("PINECONE_INDEX", "smra-index")
    api_key = os.getenv("PINECONE_API_KEY")
    env = os.getenv("PINECONE_ENV") or os.getenv("PINECONE_ENVIRONMENT")

    logger.info(f"PINECONE_INDEX={index_name} PINECONE_API_KEY_set={bool(api_key)} PINECONE_ENV={env}")

    # Prepare upsert payload: (id, vector, metadata)
    items = []
    for i, vec in enumerate(vectors):
        vid = f"doc-{i:06d}"
        meta = metadatas[i] if i < len(metadatas) else {}
        meta = dict(meta) if isinstance(meta, dict) else {"source": str(meta)}
        # LangChain PineconeVectorStore expects the raw chunk text under the "text" key
        # when reconstructing Documents from query results.
        if i < len(texts) and "text" not in meta:
            meta["text"] = texts[i]
        items.append((vid, vec, meta))

    # Try pinecone-client (legacy style)
    try:
        import pinecone as pc
        logger.info("Using pinecone client (pinecone.init)...")
        if hasattr(pc, "init"):
            pc.init(api_key=api_key, environment=env)
            idx = pc.Index(index_name)
            # clear index (best-effort)
            try:
                idx.delete(delete_all=True)
                logger.info("Cleared existing index via pinecone.Index.delete")
            except Exception:
                logger.info("Could not clear index via pinecone client; continuing")

            # Upsert in batches
            batch_size = 50
            for i in range(0, len(items), batch_size):
                batch = items[i:i+batch_size]
                logger.info(f"Upserting batch {i//batch_size+1} ({len(batch)} vectors)...")
                idx.upsert(vectors=batch)
            stats = idx.describe_index_stats()
            count = getattr(stats, "total_vector_count", None) or stats.get("total_vector_count")
            logger.info(f"✅ Pinecone now has {count} vectors (via pinecone client)")
            return
    except Exception as e:
        logger.warning(f"pinecone client upload failed or not available: {e}")

    # Try new-style Pinecone SDK (from pinecone import Pinecone)
    try:
        from pinecone import Pinecone
        logger.info("Using Pinecone SDK (Pinecone class)...")
        pc2 = Pinecone(api_key=api_key)
        idx2 = pc2.Index(index_name)
        try:
            idx2.delete(delete_all=True)
            logger.info("Cleared existing index via Pinecone.Index.delete")
        except Exception:
            logger.info("Could not clear index via Pinecone.Index.delete; continuing")

        batch_size = 50
        for i in range(0, len(items), batch_size):
            batch = items[i:i+batch_size]
            # Pinecone SDK v3 expects payload differently depending on wrapper; try upsert kv format
            try:
                idx2.upsert(vectors=[{"id": vid, "values": vec, "metadata": meta} for vid, vec, meta in batch])
            except Exception:
                try:
                    idx2.upsert(vectors=batch)
                except Exception as e:
                    logger.error(f"Batch upsert failed (Pinecone SDK): {e}")
        try:
            stats = idx2.describe_index_stats()
            count = getattr(stats, "total_vector_count", None) or stats.get("total_vector_count")
            logger.info(f"✅ Pinecone now has {count} vectors (via Pinecone SDK)")
        except Exception:
            logger.info("Upload complete (couldn't verify stats)")
        return
    except Exception as e:
        logger.warning(f"Pinecone SDK not available or failed: {e}")

    logger.error("No Pinecone client available; please install pinecone-client or configure PINECONE_API_KEY")


if __name__ == "__main__":
    upload_direct_vectors()
