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
*** Begin merged README for repo root — comprehensive SMRA guide ***

# Stock Market Research Assistant (SMRA)

> AI-powered investment research assistant combining RAG, Text-to-SQL, and Live Web Search.

This repository contains a small demo Streamlit application that demonstrates:
- Natural language → SQL queries against a local SQLite stock prices DB
- Retrieval-Augmented Generation (RAG) over uploaded financial PDFs (Pinecone or local HuggingFace embeddings)
- Live web search via the Tavily API

The application is intended as an educational/research prototype showing how to combine structured and unstructured financial data sources with LLMs.

Contents
--------
- Overview & architecture
- Tech stack
- End-to-end setup (install, environment, data load, ingestion, OCR)
- Running the app and test scripts
- Troubleshooting notes
- Project structure and files
- Data & references
- License & disclaimer

## Overview & architecture

SMRA receives a user query, routes intent (SQL / RAG / WEB / HYBRID) and sends the request to one or more specialized agents. Each agent synthesizes an answer and the system returns a concise, cited response.

Architecture (logical):

```
User Query
	 ↓
Intent Router (LLM)
	 ↓
┌─────────┬──────────┬─────────┐
│ SQL     │ RAG      │ WEB     │
│ Agent   │ Agent    │ Agent   │
└────┬────┴────┬─────┴────┬────┘
	  ↓         ↓          ↓
  SQLite    Pinecone   Tavily API
  (OHLCV)  (10-K PDFs) (Live news)
	  ↓         ↓          ↓
		  Response Synthesizer
					 ↓
			Streamlit Chat UI
```

Agents
- SQL Agent: NL→SQL, executes against local SQLite (with fallback behavior for missing dates), synthesizes the answer.
- RAG Agent: Searches vector store (Pinecone or local fallback), extracts text from OCR'd PDFs, and answers filing questions.
- Web Agent: Calls Tavily for live news, returns sentiment and source citations.

## Tech stack

| Component     | Technology |
|---------------|------------|
| LLM           | Groq / Ollama / Gemini (configurable via `LLM_PROVIDER`) |
| Vector store  | Pinecone (preferred) — local pickle fallback supported |
| Embeddings    | sentence-transformers/all-MiniLM-L6-v2 (384-dim) |
| Database      | SQLite (pandas helper loader) |
| Web search    | Tavily API |
| OCR           | PyMuPDF + pytesseract (pdf2image) |
| UI            | Streamlit |
| Framework     | LangChain (for orchestration) |

## End-to-end setup (from scratch)

1) Install dependencies (run from repo root):

```bash
python -m pip install -r smra/requirements.txt
```

2) Create environment file for secrets: create `smra/.env` (copy `smra/.env.example` if present).

Example `.env`
----------------
Create `smra/.env` from the example below and fill in your API keys and paths. Do NOT commit real secrets.

```env
# LLM provider and keys
LLM_PROVIDER=groq            # groq | ollama | gemini
GROQ_API_KEY=gsk_your_groq_key_here
GROQ_MODEL=mixtral-8x7b-32768

# Pinecone (RAG)
PINECONE_API_KEY=your_pinecone_api_key_here
PINECONE_ENV=us-west1-gcp
PINECONE_INDEX=smra-index
PINECONE_DIMENSION=384        # must match embedding model dims
PINECONE_DISABLED=0           # set to 1 to force local rag_local_store.pkl

# Embeddings model
EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2

# Tavily (web search)
TAVILY_API_KEY=tvly_your_key_here

# OCR (Windows examples)
TESSERACT_CMD=C:\\Program Files\\Tesseract-OCR\\tesseract.exe
POPPLER_PATH=C:\\path\\to\\poppler\\bin
OCR_MAX_PAGES=5               # 0 = all pages, >0 limit for tests
OCR_FORCE=0                   # 1 = force OCR (skip text-first extraction)

# Database
DATABASE_PATH=smra/data/smra.db

# Misc
LOG_LEVEL=INFO
```

Notes:
- `PINECONE_DIMENSION` must match the dimension of `EMBEDDING_MODEL` (the project uses 384 for `all-MiniLM-L6-v2`).
- Set `PINECONE_DISABLED=1` when you want to run offline and use the local RAG store `smra/data/rag_local_store.pkl`.
- On Windows, either add Tesseract and Poppler to PATH or set `TESSERACT_CMD` and `POPPLER_PATH`.

Minimal environment variables (examples):

```env
LLM_PROVIDER=groq            # or ollama, gemini
GROQ_API_KEY=gsk_xxxxxxxxxxxx
GROQ_MODEL=mixtral-8x7b-32768
PINECONE_API_KEY=xxxxxxxxxxxx
PINECONE_INDEX=smra-index
TAVILY_API_KEY=tvly-xxxxxxxxxxxx
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
POPPLER_PATH=C:\path\to\poppler\bin
PINECONE_DISABLED=0          # set to 1 to force local RAG store
OCR_MAX_PAGES=5              # shorten for tests
OCR_FORCE=0                  # 1 to force OCR path
```

Notes:
- If you do not have Pinecone credentials or want to run offline, set `PINECONE_DISABLED=1`. The ingestion script will instead save `smra/data/rag_local_store.pkl` which the RAG agent can use.
- On Windows, either add Tesseract and Poppler to PATH or set `TESSERACT_CMD` and `POPPLER_PATH` in `.env`.

3) Load the bundled Excel stock data into SQLite (default path `smra/data/stock_market_data.xlsx`):

```bash
python smra/data/load_db.py
```

If you have a custom Excel file or want a specific DB path:

```bash
python smra/data/load_db.py --excel path/to/your.xlsx --db smra/data/smra.db --set-columns
```

4) Ingest financial PDFs for RAG (one-time):

- Drop annual reports / 10-K PDFs into `smra/pdfs/`.
- Run ingestion (this will OCR pages as needed, chunk text, embed using the configured embedding model, and either upload to Pinecone or save a local fallback store):

```bash
python smra/scripts/ingest_pdfs.py
python smra/scripts/upload_to_pinecone.py   # optional if you use Pinecone
```

Important: the project uses `sentence-transformers/all-MiniLM-L6-v2` (384 dims). If you previously created a Pinecone index with different dimensions (e.g., 1536), delete and recreate it with `dimension=384`.

5) OCR prerequisites (if PDFs are scanned/image-only):

- Install Tesseract and add it to PATH or set `TESSERACT_CMD`.
- Install Poppler (for `pdftoppm`) and add its `bin` folder to PATH or set `POPPLER_PATH`.

Optional environment flags for quicker testing:

- `OCR_MAX_PAGES=5` — limits pages processed for speed.
- `OCR_FORCE=1` — skip text-first path and force OCR (useful for known scanned PDFs).

6) Run the Streamlit app:

```bash
cd smra
streamlit run app.py
# or from repo root: streamlit run smra/app.py
```

## Helpful test scripts (headless checks)

Run small helper scripts (from repo root):

```bash
python smra/scripts/test_sql_agent.py
python smra/scripts/test_router.py
python smra/scripts/test_web_agent.py
```

These exercise individual components without launching the UI.

## Troubleshooting (common issues)

- Groq/GROQ_API_KEY errors: ensure `smra/.env` contains the correct key and restart Streamlit so `python-dotenv` reloads it.
- "no such table: stock_prices": re-run the loader:

```bash
python smra/data/load_db.py
```

- Pinecone dimension mismatch: recreate your index with `dimension=384` when using `all-MiniLM-L6-v2`.
- Windows quoting issues: use the provided scripts in `smra/scripts/` where possible instead of `python -c '...'` one-liners.
- If Pinecone is slow/unreachable, set `PINECONE_DISABLED=1` to force using the local `smra/data/rag_local_store.pkl` store.

Behavior notes
- SQL agent: when a requested date is missing, the agent attempts a nearest-date fallback and will explain the fallback in its response.

## Project structure (key files)

```
smra/
├── app.py                  # Streamlit chat UI
├── router.py               # Intent classification (routes to SQL/RAG/WEB/HYBRID)
├── agents/
│   ├── sql_agent.py        # NL → SQL → answer
│   ├── rag_agent.py        # PDF retrieval + answer
│   └── web_agent.py        # Tavily search + sentiment
├── utils/
│   ├── llm.py              # unified LLM wrapper (Groq / Ollama / Gemini)
│   ├── charts.py           # Plotly chart helpers
│   └── schemas.py          # response schemas
├── data/
│   ├── load_db.py          # Excel → SQLite loader
│   ├── smra.db             # optional bundled DB
│   └── rag_local_store.pkl # local RAG fallback
├── scripts/
│   ├── ingest_pdfs.py      # OCR + chunk + embed PDFs
│   ├── upload_to_pinecone.py
│   └── test_*.py           # small test helpers
├── pdfs/                   # place PDFs for ingestion
└── .env                    # API keys (never commit)
```

## Data

Structured (SQL): daily OHLCV data (7,560 rows) for ~30 symbols (2025 sample) used for NL→SQL examples.

Unstructured (RAG): example Apple 10-K and NVIDIA Annual Report OCR texts chunked into ~250 vectors at 384 dimensions.

## Industry references

- FinRobot — https://github.com/AI4Finance-Foundation/FinRobot
- FinGPT — https://github.com/AI4Finance-Foundation/FinGPT
- FinStat2SQL (research)

## Notes about READMEs

We keep the detailed usage and developer notes in `smra/README.md` for module-level documentation and quick local edits. This root `README.md` is now the canonical, end-to-end guide for the repository and includes everything from the `smra/README.md` (duplicates removed).

If you prefer, we can:
- remove `smra/README.md` and keep only this root README, or
- keep both and add a short pointer at the top of `smra/README.md` to avoid drift (recommended).

## License

MIT

## Disclaimer

This tool is for educational and research purposes only and is not financial advice. Consult a licensed financial advisor before making investment decisions.

*** End merged README ***
