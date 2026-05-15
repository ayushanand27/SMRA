# Stock Market Research Assistant (SMRA)

AI-powered investment research assistant using RAG + Text-to-SQL + Live Web Search.

This repository contains a small demo app (Streamlit) that demonstrates:
- Natural language → SQL queries against a local SQLite stock prices DB
- RAG over uploaded financial PDFs (Pinecone + local HuggingFace embeddings)
- Live web search via Tavily

Quick start
-----------
1. Install dependencies (run from repository root):

```bash
python -m pip install -r smra/requirements.txt
```

2. Create a `.env` file in `smra/` (copy `.env.example` if present) and set your keys. Minimal vars:

```
LLM_PROVIDER=groq        # or ollama, gemini
GROQ_API_KEY=sk_...      # if using groq
PINECONE_API_KEY=...     # for Pinecone (RAG)
PINECONE_INDEX=smra-index
TAVILY_API_KEY=...       # for web agent
```

3. Load the bundled Excel data into SQLite (defaults to `smra/data/stock_market_data.xlsx`):

```bash
python smra/data/load_db.py
```

If you have your own Excel file, pass it explicitly:

```bash
python smra/data/load_db.py --excel path/to/your.xlsx --db smra/data/smra.db --set-columns
```

4. Ingest PDFs for RAG (drop PDFs into `smra/pdfs/` and run):

```bash
python smra/scripts/ingest_pdfs.py
```

This uses `sentence-transformers/all-MiniLM-L6-v2` (384 dims). If you previously created a Pinecone index with 1536 dims, delete it and recreate with `dimension=384`.

Note: If Pinecone is unreachable or you don't have an API key, the ingestion script will save a local fallback store at `smra/data/rag_local_store.pkl`. The RAG agent will automatically use this local store when Pinecone cannot be contacted.

OCR setup for scanned PDFs
--------------------------
If your PDFs are scanned/image-only (no selectable text), the ingestion step will attempt OCR. The pipeline checks for text first, then falls back to OCR (pytesseract via pdf2image). Optional: if `pytreact` is installed, it is tried first; if the `ocrmypdf` CLI is installed, it may be used to generate a searchable PDF.

Windows prerequisites (recommended):
- Install **Tesseract OCR** and add `tesseract.exe` to your PATH.
- Install **Poppler** (for `pdftoppm`) and add its `bin` folder to PATH.

If you don't want to modify PATH, you can set these in `.env` instead:

```
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
POPPLER_PATH=C:\path\to\poppler\bin
OCR_MAX_PAGES=5
OCR_FORCE=1
PINECONE_DISABLED=1
```

Tip: set `OCR_MAX_PAGES` to a small number for faster test runs, then remove it (or set to 0) for full ingestion.
Tip: set `OCR_FORCE=1` to skip slow direct text extraction and go straight to OCR for scanned PDFs.
Tip: set `PINECONE_DISABLED=1` to force local RAG store usage (useful if Pinecone is slow/unreachable).

Python packages (already in `requirements.txt`):
- `pytesseract`
- `pdf2image`
- `pillow`

After installing OCR prerequisites, re-run:

```bash
python smra/scripts/ingest_pdfs.py
```

5. Run the Streamlit app:

```bash
streamlit run smra/app.py
# or
cd smra
streamlit run app.py
```

Helpful test scripts
--------------------
There are small helper scripts in `smra/scripts/` to validate the pieces without the UI:

- `test_sql_agent.py` — runs a dry NL→SQL→SQLite test
- `test_router.py` — checks routing (SQL / WEB / RAG)
- `test_web_agent.py` — runs the web agent (Tavily)

Run them from the repo root:

```bash
python smra/scripts/test_sql_agent.py
python smra/scripts/test_router.py
python smra/scripts/test_web_agent.py
```

Troubleshooting
---------------
- Groq/GROQ_API_KEY errors: ensure `smra/.env` contains the key and restart Streamlit/tests so `load_dotenv()` takes effect.
- "no such table: stock_prices": re-run the loader:

```bash
python smra/data/load_db.py
```

- Pinecone dimension mismatch: when switching embeddings to `all-MiniLM-L6-v2` recreate your index with `dimension=384`.

- Windows quoting issues: use the provided scripts in `smra/scripts/` instead of `python -c "..."`.

- SQL agent behavior: if you ask for a specific date that is missing from the DB, the SQL agent will now try to return the nearest available date (or the most recent) for the requested ticker and will explain the fallback.

Project overview
----------------
- `smra/app.py` — Streamlit UI and router wiring
- `smra/router.py` — intent classification (routes to SQL/RAG/WEB)
- `smra/agents/sql_agent.py` — NL→SQL, execute on local SQLite, synthesize answer
- `smra/agents/rag_agent.py` — PDF ingestion & RAG via Pinecone
- `smra/agents/web_agent.py` — Tavily live web search
- `smra/utils/llm.py` — unified LLM wrapper (Groq / Ollama / Gemini)
- `smra/data/load_db.py` — Excel→SQLite loader (creates `idx_sym_date` index)
- `smra/scripts/` — convenience scripts (ingest, tests, fix_and_load)

License
-------
MIT
