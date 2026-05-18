import os
import sys
import pickle
from pathlib import Path
from dotenv import load_dotenv

# Prepare environment and imports so this can be run from the repo root or from smra/
script_dir = Path(__file__).resolve().parent
import os
import sys
import pickle
import logging
from pathlib import Path
from dotenv import load_dotenv

# Load env from smra/.env so the script can be run from repo root
script_dir = Path(__file__).resolve().parent
smra_root = script_dir.parent
env_path = smra_root / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)
else:
    load_dotenv(override=True)

sys.path.insert(0, str(smra_root))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("smra.ingest")


def extract_text_from_pdf(pdf_path: str) -> list[dict]:
    """Extract text per-page from a PDF. Uses PyMuPDF (fitz) then per-page OCR fallback via pytesseract."""
    try:
        import fitz
    except Exception:
        logger.error("pymupdf (fitz) is required. Install with: pip install pymupdf")
        raise

    chunks = []
    doc = fitz.open(pdf_path)
    filename = Path(pdf_path).name

    logger.info(f"Processing {filename} ({len(doc)} pages)...")

    for page_num in range(len(doc)):
        page = doc[page_num]
        try:
            text = page.get_text("text") or ""
        except Exception:
            text = ""
        text = text.strip()

        if len(text) > 50:
            chunks.append({"text": text, "page": page_num + 1, "source": filename})
            continue

        # OCR fallback
        logger.info(f"  Page {page_num+1}: no text layer, using OCR...")
        try:
            import pytesseract
            from PIL import Image

            tesseract_cmd = os.getenv("TESSERACT_CMD", r"C:\\Program Files\\Tesseract-OCR\\tesseract.exe")
            if tesseract_cmd and Path(tesseract_cmd).exists():
                pytesseract.pytesseract.tesseract_cmd = str(tesseract_cmd)

            mat = fitz.Matrix(2, 2)
            pix = page.get_pixmap(matrix=mat)
            img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            ocr_text = pytesseract.image_to_string(img, lang="eng") or ""
            ocr_text = ocr_text.strip()

            if len(ocr_text) > 50:
                chunks.append({"text": ocr_text, "page": page_num + 1, "source": filename})
                logger.info(f"  Page {page_num+1}: OCR extracted {len(ocr_text)} chars")
            else:
                logger.warning(f"  Page {page_num+1}: OCR found no text, skipping")

        except Exception as e:
            logger.error(f"  Page {page_num+1}: OCR failed: {e}")

    doc.close()
    logger.info(f"Extracted {len(chunks)} pages from {filename}")
    return chunks


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 150) -> list[str]:
    words = text.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i:i + chunk_size])
        chunks.append(chunk)
        i += chunk_size - overlap
    return chunks


def ingest_pdfs(pdf_folder: str):
    """Extract PDFs, produce embeddings, save a local rag store, and optionally upload to Pinecone."""
    try:
        from langchain.schema import Document
        from langchain_huggingface import HuggingFaceEmbeddings
    except Exception:
        logger.error("Please install langchain and langchain_huggingface: pip install langchain langchain-huggingface")
        raise

    # Attempt to import pinecone clients if available
    try:
        from langchain_pinecone import Pinecone as LangchainPinecone
        from pinecone import Pinecone
    except Exception:
        LangchainPinecone = None
        try:
            from pinecone import Pinecone
        except Exception:
            Pinecone = None

    pdf_files = list(Path(pdf_folder).glob("*.pdf"))
    if not pdf_files:
        logger.error("No PDFs found!")
        return

    logger.info(f"Found {len(pdf_files)} PDF files")

    all_docs = []
    for pdf_path in pdf_files:
        pages = extract_text_from_pdf(str(pdf_path))
        for page_data in pages:
            text_chunks = chunk_text(page_data["text"])
            for chunk in text_chunks:
                if len(chunk.strip()) > 30:
                    all_docs.append(Document(page_content=chunk, metadata={"source": page_data["source"], "page": page_data["page"]}))

    if not all_docs:
        logger.error("No text extracted from any PDF!")
        return

    logger.info(f"Total chunks to upload: {len(all_docs)}")

    logger.info("Loading embedding model...")
    embeddings = HuggingFaceEmbeddings(model_name="sentence-transformers/all-MiniLM-L6-v2", model_kwargs={"device": "cpu"})

    # Build local RAG store (pickle) so the app can use local fallback when Pinecone is disabled
    texts = [d.page_content for d in all_docs]
    metadatas = [d.metadata for d in all_docs]

    try:
        vectors = embeddings.embed_documents(texts)
    except Exception as e:
        logger.error(f"Failed to compute embeddings: {e}")
        raise

    local_store = {"texts": texts, "metadatas": metadatas, "vectors": vectors}
    data_dir = smra_root / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    local_store_path = data_dir / "rag_local_store.pkl"
    with open(local_store_path, "wb") as f:
        pickle.dump(local_store, f)
    logger.info(f"Saved local RAG store to: {local_store_path}")

    index_name = os.getenv("PINECONE_INDEX", "smra-index")

    # Try to clear existing Pinecone index and upload if possible
    if Pinecone is not None and LangchainPinecone is not None:
        try:
            pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
            idx = pc.Index(index_name)
            try:
                idx.delete(delete_all=True)
                logger.info("Cleared old Pinecone vectors")
            except Exception:
                logger.info("Could not clear index via delete_all, continuing")
        except Exception as e:
            logger.warning(f"Could not connect to Pinecone (will continue): {e}")

    # Upload in batches via langchain_pinecone if available
    batch_size = 50
    total_batches = (len(all_docs) - 1) // batch_size + 1
    for i in range(0, len(all_docs), batch_size):
        batch = all_docs[i:i + batch_size]
        batch_num = i // batch_size + 1
        logger.info(f"Uploading batch {batch_num}/{total_batches}...")
        try:
            if LangchainPinecone is not None:
                LangchainPinecone.from_documents(batch, embeddings, index_name=index_name)
            else:
                logger.info("langchain_pinecone not available; skipped remote upload for this batch")
        except Exception as e:
            logger.error(f"Batch {batch_num} failed: {e}")

    # Final verification if Pinecone available
    if Pinecone is not None:
        try:
            pc = Pinecone(api_key=os.getenv("PINECONE_API_KEY"))
            stats = pc.Index(index_name).describe_index_stats()
            count = getattr(stats, "total_vector_count", None) or stats.get("total_vector_count")
            logger.info(f"✅ Done! Pinecone now has {count} vectors")
        except Exception as e:
            logger.warning(f"Could not verify Pinecone index stats: {e}")
    else:
        logger.info("Done. Local RAG store ready; Pinecone not configured or libraries missing.")


if __name__ == "__main__":
    pdf_dir = smra_root / "pdfs"
    logger.info(f"Starting ingestion from: {pdf_dir}")
    ingest_pdfs(str(pdf_dir))
    
