# 📈 Stock Market Research Assistant (SMRA)

> An AI-powered investment research assistant combining RAG, Text-to-SQL, and Live Web Search — inspired by production systems at Franklin Templeton and Morgan Stanley.

---

## What It Does

SMRA answers natural language questions about stocks and financial filings by automatically routing each query to the right data source:

| Query Type | Example | Data Source |
|---|---|---|
| Historical prices | "What was NVDA closing price in Jan 2025?" | SQLite DB (7,560 rows) |
| Financial filings | "What was Apple total net sales?" | Pinecone RAG (250 vectors) |
| Live news | "Latest news about Tesla?" | Tavily Web Search |
| Hybrid | "Why did NVDA drop last week?" | SQL + WEB combined |

---

## Architecture

```
User Query
    ↓
Intent Router (Groq LLM)
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

### Three Agents

**SQL Agent** — Converts natural language to SQL, executes against SQLite, synthesizes answer. Auto-retries with repaired query on failure.

**RAG Agent** — Rewrites vague queries, searches Pinecone vector store (384-dim embeddings), extracts financial figures from OCR'd PDF text. Falls back to local store if Pinecone unavailable.

**Web Agent** — Fetches live news via Tavily, returns sentiment score and source citations. Results cached for 1 hour.

---

## Tech Stack

| Component | Technology |
|---|---|
| LLM | Groq (mixtral-8x7b-32768) |
| Vector Store | Pinecone (cosine similarity) |
| Embeddings | sentence-transformers/all-MiniLM-L6-v2 |
| Database | SQLite via pandas |
| Web Search | Tavily API |
| OCR | PyMuPDF + Tesseract |
| UI | Streamlit |
| Framework | LangChain |

---

## Project Structure

```
smra/
├── app.py                  # Streamlit chat UI
├── router.py               # Intent classification (SQL/RAG/WEB/HYBRID)
├── agents/
│   ├── sql_agent.py        # NL → SQL → answer
│   ├── rag_agent.py        # PDF retrieval + answer
│   └── web_agent.py        # Tavily search + sentiment
├── utils/
│   ├── llm.py              # Groq wrapper with retry + fallback
│   ├── charts.py           # Plotly chart helpers
│   └── schemas.py          # Structured response schemas
├── data/
│   ├── load_db.py          # Excel → SQLite loader
│   ├── smra.db             # 7,560 rows, 30 symbols, 2025
│   └── rag_local_store.pkl # Local RAG fallback
├── scripts/
│   ├── ingest_pdfs.py      # OCR + chunk + embed PDFs
│   └── upload_to_pinecone.py
├── pdfs/                   # Apple + NVIDIA 10-K filings
├── references/
│   ├── FinRobot/           # Reference: AI4Finance Foundation
│   └── FinGPT/             # Reference: Yang et al. 2023
└── .env                    # API keys (never committed)
```

---

## Setup

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Configure environment
Create `.env` in the `smra/` folder:
```env
GROQ_API_KEY=gsk_xxxxxxxxxxxx
PINECONE_API_KEY=xxxxxxxxxxxx
PINECONE_INDEX=smra-index
TAVILY_API_KEY=tvly-xxxxxxxxxxxx
GROQ_MODEL=mixtral-8x7b-32768
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

### 3. Load stock data into SQLite
```bash
python data/load_db.py
```

### 4. Ingest financial PDFs (one-time)
Drop PDF annual reports into `pdfs/` folder, then:
```bash
python scripts/ingest_pdfs.py
python scripts/upload_to_pinecone.py
```

### 5. Run the app
```bash
streamlit run app.py
```

---

## Data

**Structured (SQL):** 7,560 rows of daily OHLCV data for 30 symbols across 6 sectors (Technology, Financials, Healthcare, Energy, Consumer Discretionary, Consumer Staples) for the full year 2025.

**Unstructured (RAG):** Apple 10-K (FY2023) and NVIDIA Annual Report — OCR-extracted and chunked into 250 vectors at 384 dimensions.

---

## Industry References

This project's architecture is inspired by and validated against:

1. **FinRobot** (AI4Finance Foundation, ICAIF 2024)
   Multi-agent platform for financial analysis using LLMs
   https://github.com/AI4Finance-Foundation/FinRobot

2. **FinGPT** (Yang et al., arXiv:2306.06031, 2023)
   Open-source financial LLMs with RAG and sentiment analysis
   https://github.com/AI4Finance-Foundation/FinGPT

3. **FinStat2SQL** (arXiv:2506.23273, 2025)
   Text-to-SQL pipeline for financial statement analysis

4. **Franklin Templeton Production RAG** (Databricks, 2025)
   Enterprise RAG supporting 300+ financial advisors — same architecture as SMRA

5. **Morgan Stanley AI Research Agents**
   Retrieval-based AI agents for internal financial research workflows

---

## Disclaimer

This tool is for educational and research purposes only. Nothing in this application constitutes financial advice. Always consult a licensed financial advisor before making investment decisions.
