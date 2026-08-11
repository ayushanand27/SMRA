---
title: SMRA — Stock Market Research Assistant
emoji: 📈
colorFrom: blue
colorTo: green
sdk: docker
app_port: 7860
pinned: false
---

# Stock Market Research Assistant (SMRA)

[![CI](https://github.com/ayushanand27/SMRA/actions/workflows/ci.yml/badge.svg)](https://github.com/ayushanand27/SMRA/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

**SMRA** is a production-minded multi-agent financial research system: ask natural-language questions and get grounded answers from **structured market data**, **company filings**, and **live web search**. Built for engineers and researchers who need a credible demo of LLM orchestration, RAG, Text-to-SQL, and operational guardrails—not a toy chatbot.

Streamlit UI + FastAPI API · Groq/Ollama/Gemini · Postgres · Pinecone · Langfuse

**Public deploy (free stack):** [Hugging Face Spaces](https://huggingface.co/spaces) (Docker) + [Neon](https://neon.tech) Postgres + [Upstash](https://upstash.com) Redis — see [Cloud deploy](#cloud-deploy-neon--upstash--hugging-face-spaces).

---

## Architecture

```mermaid
flowchart TB
    U[User Query] --> UI[Streamlit UI / FastAPI]
    UI --> GR[Input Guardrails]
    GR --> R[Intent Router<br/>LLM + keyword fallback]
    R --> SQL[SQL Agent<br/>NL → SELECT → synthesize]
    R --> RAG[RAG Agent<br/>hybrid retrieval + citations]
    R --> WEB[Web Agent<br/>Tavily live search]
    R --> HY[HYBRID<br/>SQL + RAG orchestrator]
    SQL --> PG[(Postgres<br/>stock_prices)]
    RAG --> PC[(Pinecone<br/>8 filing PDFs)]
    RAG -. fallback .-> PKL[rag_local_store.pkl]
    WEB --> TV[Tavily API]
    SQL --> LF[Langfuse traces]
    RAG --> LF
    WEB --> LF
    HY --> LF
    UI --> AUD[(SQLite audit.db)]
    UI --> LOG[Structured logs<br/>query_id · latency · cost]
    API --> REDIS[(Redis<br/>rate-limit store)]
    API --> ING[APScheduler<br/>yfinance ingestion]
    ING --> PG
```

**Request flow:** guardrails → router → specialist agent(s) → synthesis with citations → audit log. FastAPI also runs scheduled live ingestion when `DATABASE_URL` points at Postgres.

---

## Key Features

### Multi-agent routing & orchestration
- LLM intent router (`SQL` / `RAG` / `WEB` / `HYBRID`) with deterministic keyword fallback
- HYBRID mode runs SQL + RAG in parallel and synthesizes one coherent answer
- Unified response schemas, expandable routes, and per-request `query_id` for tracing

### Live market data (50 tickers · US + India)
- **30 US** large-caps + **20 NSE** symbols (`.NS` suffix via yfinance)
- Scheduled ingestion (APScheduler on FastAPI startup): fetch OHLCV + fundamentals → Postgres upsert
- TTL read cache on SQL queries to reduce DB load between ingestion cycles
- Explicit **`currency`** column (`USD` / `INR`)—no silent cross-currency comparison
- SQLite fallback when `DATABASE_URL` is unset (local dev only)

### RAG over 8 real company filings
- PDFs: Apple, NVIDIA, Amazon, Microsoft, Tesla, JPMorgan Chase, TCS, Reliance
- PyMuPDF text extraction + Tesseract OCR for scanned pages
- Chunk metadata: `source`, `page`, `ticker`, `doc_type`, `fiscal_year`
- Hybrid retrieval: dense vectors + BM25 fusion + cross-encoder rerank
- Answers include **`[Source: filename, page X]`** citations; numeric faithfulness checks flag ungrounded figures

### Security
- OWASP LLM Top 10–aligned **input guardrails** (prompt injection, SQL abuse, length limits)
- Output sanitization; SQL agent restricted to **`SELECT`-only** with banned-statement regex
- Optional **`X-API-Key`** auth (constant-time comparison, fail-closed when enabled)
- **Redis-backed sliding-window rate limiting** (`RATE_LIMIT_PER_MIN` per key/IP); graceful in-memory fallback if Redis is down
- **CORS + security headers** on the FastAPI service (`CORS_ALLOWED_ORIGINS` allow-list; `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Strict-Transport-Security` on every response)
- **`ENV=production` startup gate:** the API refuses to boot if `AUTH_ENABLED`/`RATE_LIMIT_ENABLED` are off while `ENV=production`, so an insecure config can't reach prod by accident
- **Docker image runs as a non-root user** (`appuser`), not root
- **LLM provider failover:** if the primary Groq call hard-fails, `call_llm` automatically retries via Gemini when `GEMINI_API_KEY`/`GOOGLE_API_KEY` is configured, instead of surfacing an error
- **Secrets hygiene:** only `.env.example` files (placeholder values) are tracked in git — `.gitignore` blocks every other `.env*` variant, plus `*.db`/`*.sqlite*` binaries. **Gitleaks** scans every commit in CI and as a `pre-commit` hook (`.pre-commit-config.yaml`) so a secret is caught before it lands, not after. Never commit a real `.env` or any file containing live keys/connection strings — if one ever is, treat it as compromised: rotate it at the provider immediately, since removing the file from a later commit does **not** remove it from git history (`git filter-repo`/BFG + force-push are required to actually scrub it)

### Observability & audit
- Structured JSON logs: latency, token usage, estimated cost per LLM call
- Optional **Langfuse** tracing on every `call_llm` invocation
- SQLite **audit trail** (`/audit` API)—every query persisted for replay and debugging

### Evaluation
- Golden dataset for routing + guardrail regression (`smra/eval/golden_dataset.json`)
- Offline eval runner in CI (`python -m smra.eval.run_eval`)
- Optional **LLM-as-judge** scoring (`--judge`) for answer quality
- Faithfulness helper validates numeric claims against retrieved context

### Quality & delivery
- **86** automated unit tests (pytest, ~38% line coverage, enforced floor 35% via `pytest-cov`) + offline eval suite (100% routing accuracy on the golden set)
- **GitHub Actions CI:** ruff lint + pytest + golden evals across **Python 3.10/3.11/3.12**, a dedicated Gitleaks secret-scan job, and a Docker image build check
- **Dependabot** for pip, GitHub Actions, and Docker base-image updates
- **`smra/db/migrate.py`:** tracked, idempotent Postgres migration runner (`schema_migrations` table) — safe to re-run against any environment
- CODEOWNERS, PR template, and issue templates; changes tracked in [`CHANGELOG.md`](CHANGELOG.md)
- **Docker Compose** one-command Postgres + Redis + FastAPI stack
- **Dockerfile** with Tesseract + Poppler for OCR-capable ingestion, running as a non-root user
- Optional **semantic answer cache** (`SEMANTIC_CACHE_ENABLED`) for similar-query reuse

---

## Tech Stack

| Category | Technologies |
|----------|--------------|
| **LLM / orchestration** | Groq, Ollama, Gemini (`LLM_PROVIDER`); LangChain (RAG ingestion); custom router + orchestrator |
| **UI / API** | Streamlit, FastAPI, Uvicorn |
| **Structured data** | PostgreSQL (primary), SQLAlchemy, psycopg2, yfinance, APScheduler |
| **Vector store** | Pinecone (384-dim cosine); local `rag_local_store.pkl` fallback |
| **Embeddings / retrieval** | `sentence-transformers/all-MiniLM-L6-v2`, BM25, cross-encoder rerank |
| **Web search** | Tavily API |
| **Document processing** | PyMuPDF, pytesseract, pdf2image, Poppler |
| **Security / limits** | Custom guardrails, HMAC API keys, Redis sliding-window rate limit, CORS + security headers, Gitleaks |
| **Observability** | Langfuse, structured logging, SQLite audit DB |
| **Infra** | Docker (non-root), Docker Compose, GitHub Actions (matrix + secret-scan + Docker build), Dependabot, pre-commit, python-dotenv centralized config |

---

## Quick Start

### 1. Clone & install

```bash
git clone https://github.com/ayushanand27/SMRA.git
cd SMRA
python -m pip install -r smra/requirements.txt
python -m pip install -r smra/requirements-dev.txt   # pytest, ruff
```

### 2. Configure environment

```bash
cp smra/.env.example smra/.env
# Edit smra/.env — at minimum: GROQ_API_KEY, PINECONE_API_KEY, TAVILY_API_KEY
```

### 3. One-command stack (Docker Compose — recommended)

```bash
cp smra/.env.example smra/.env
# Edit smra/.env — add GROQ_API_KEY, PINECONE_API_KEY, TAVILY_API_KEY

docker compose up -d --build
```

This starts **Postgres** (host port `5434`), **Redis** (`6379`), and **FastAPI** (`8010`).  
Compose overrides `DATABASE_URL` / `REDIS_URL` to use in-network hostnames.

**First-time DB seed** (run on host while compose is up):

```bash
python smra/data/load_db.py
python -m smra.scripts.migrate_sqlite_to_postgres --truncate
python smra/scripts/ingest_pdfs.py
```

**Applying schema changes to an existing Postgres DB** (e.g. after `git pull`, or against Neon in
prod) — no need to re-run the full SQLite migration:

```bash
python -m smra.db.migrate
```

Tracks applied migrations in a `schema_migrations` table, so `smra/db/schema_postgres.sql` and
each file under `smra/db/migrations/` run exactly once per database, in order.

**Verify API:** http://localhost:8010/health

**Streamlit** (separate terminal, on host):

```bash
python -m streamlit run smra/app.py --server.port 8501
```

<details>
<summary>Manual Docker (without Compose)</summary>

```bash
docker run -d --name smra-pg \
  -e POSTGRES_PASSWORD=smra -e POSTGRES_DB=smra \
  -p 5434:5432 postgres:16-alpine

docker run -d --name smra-redis -p 6379:6379 redis:7-alpine
```

Set in `smra/.env`:

```env
DATABASE_URL=postgresql+psycopg2://postgres:smra@127.0.0.1:5434/smra
REDIS_URL=redis://localhost:6379
```

</details>

### 4. Load historical prices (if not using compose seed step above)

```bash
# Seed SQLite from bundled Excel (if smra/data/smra.db not present)
python smra/data/load_db.py

# Copy SQLite → Postgres (includes currency backfill)
python -m smra.scripts.migrate_sqlite_to_postgres --truncate
```

### 5. Ingest filing PDFs (RAG)

Drop PDFs in `smra/pdfs/` (8 filings included in repo), then:

```bash
python smra/scripts/ingest_pdfs.py
```

Uses **384-dim** embeddings. Pinecone index must match (`PINECONE_DIMENSION=384`). Saves `smra/data/rag_local_store.pkl` as offline fallback.

**OCR (Windows):** install Tesseract + Poppler, or set `TESSERACT_CMD` / `POPPLER_PATH` in `.env`.

### 6. Run the app

```bash
# Streamlit UI (port 8501)
python -m streamlit run smra/app.py --server.port 8501

# FastAPI (port 8010) — starts ingestion scheduler + Redis rate limiting
python -m uvicorn smra.api:app --port 8010
```

| Service | URL |
|---------|-----|
| Streamlit UI | http://localhost:8501 |
| API health | http://localhost:8010/health |
| Swagger docs | http://localhost:8010/docs |

### 7. Quality gate (before PRs)

```bash
ruff check smra tests
pytest
python -m smra.eval.run_eval --threshold 0.7
# Optional (needs LLM keys):
python -m smra.eval.run_eval --judge --judge-threshold 0.6
```

---

## Design Decisions

### Postgres over SQLite for market data
Scheduled yfinance ingestion writes concurrently while the SQL agent reads. SQLite serializes writers and is a poor fit for a live pipeline. Postgres is the production path; SQLite remains an optional zero-setup fallback when `DATABASE_URL` is unset.

### Explicit `currency` column instead of suffix inference
US tickers (`AAPL`) and NSE tickers (`RELIANCE.NS`) store prices and market cap in **USD vs INR**. Inferring currency from `.NS` in prompts alone caused synthesis to label INR figures with `$`. A dedicated `currency` column—backfilled and set on every upsert—lets the SQL agent `SELECT` it and the synthesis step label `$` vs `₹` correctly. Cross-market marketcap rankings explicitly warn that **no FX conversion** is applied.

### Redis rate limiting with in-memory fallback
A process-local sliding window breaks under multiple Uvicorn workers or horizontal scale. Redis provides a shared store with the same `check_rate_limit()` interface. If Redis is unreachable at startup or mid-request, the API **logs a warning and falls back to in-memory** rather than crashing—acceptable for local dev, not ideal for multi-instance prod (documented below).

### Mock LLM mode for infra load testing (`MOCK_MODE=1`)
Load testing against live Groq/Ollama/Gemini burns **quota**, hits **429 rate limits**, and produces **noisy latency** dominated by third-party APIs—not your routing, Postgres, Redis, or caching stack. `MOCK_MODE=1` (opt-in, off by default) routes all `call_llm()` calls through fast deterministic stubs and skips Tavily/Pinecone in RAG/Web agents. Use it with `load_test.py --mode infra` (high concurrency) to measure **infra capacity**; run `--mode smoke` separately with mock off and low concurrency for **real end-to-end latency**. `/health` exposes `mock_mode: true/false` so the two modes are never confused.

---

## Screenshots

<!-- Add your own assets here -->

| Demo | File |
|------|------|
| Streamlit dark UI — SQL query | `docs/screenshots/sql-demo.png` |
| RAG answer with PDF citation | `docs/screenshots/rag-citation.png` |
| HYBRID — price + filing combined | `docs/screenshots/hybrid-demo.png` |
| Langfuse trace view | `docs/screenshots/langfuse-trace.png` |

> _Placeholder paths — replace with your recordings before publishing to LinkedIn/resume._

---

## Cloud deploy (Neon + Upstash + Hugging Face Spaces)

Free stack that keeps **all SMRA features**: Streamlit UI, FastAPI ingestion scheduler, Postgres SQL agent, Redis rate limits, Pinecone RAG, Tavily web, Langfuse.

### 1. Neon (Postgres)

1. Create a free project at [neon.tech](https://neon.tech)
2. Copy the connection string and rewrite the scheme for SQLAlchemy:
   ```text
   postgresql+psycopg2://USER:PASSWORD@ep-xxxx.region.aws.neon.tech/neondb?sslmode=require
   ```
3. From your laptop (with local `smra.db` already loaded), seed Neon once:
   ```bash
   # Temporarily set DATABASE_URL to the Neon URL in smra/.env, then:
   python smra/data/load_db.py
   python -m smra.scripts.migrate_sqlite_to_postgres --truncate
   ```

### 2. Upstash (Redis)

1. Create a free Redis DB at [upstash.com](https://upstash.com)
2. Copy the **TLS** URL (`rediss://default:...@....upstash.io:6379`)

### 3. Hugging Face Space (Docker)

1. Push this repo to GitHub (already done) or connect the HF Space to the same repo
2. Create a Space → **Docker** SDK → port **7860**
3. In Space **Settings → Variables and secrets**, add:

| Secret | Example |
|--------|---------|
| `DATABASE_URL` | Neon URL with `postgresql+psycopg2://` + `?sslmode=require` |
| `REDIS_URL` | Upstash `rediss://...` |
| `GROQ_API_KEY` | your Groq key |
| `GROQ_MODEL` | `openai/gpt-oss-20b` |
| `PINECONE_API_KEY` | your Pinecone key |
| `PINECONE_INDEX` / `PINECONE_ENV` | as in local `.env` |
| `PINECONE_DIMENSION` | `384` |
| `TAVILY_API_KEY` | your Tavily key |
| `LANGFUSE_*` | optional |
| `INGESTION_ENABLED` | `1` |
| `RATE_LIMIT_ENABLED` | `1` |

4. Build uses `Dockerfile` + `smra/scripts/start_space.sh` (FastAPI on `:8010` internal + Streamlit on `:7860` public)
5. Ensure Pinecone already has your 8 filings indexed (run `python smra/scripts/ingest_pdfs.py` locally once if needed)

**Cold start:** first request after sleep can take 1–3 minutes while the image/models load.

---

## Known Limitations & Roadmap

| Limitation | Notes / planned work |
|------------|---------------------|
| **HF Spaces cold starts** | Free Spaces sleep when idle; first wake is slow (torch + embeddings) |
| **Redis fallback is single-process** | If Redis is down, rate limits are not shared across workers |
| **Semantic cache is opt-in** | Enabling `SEMANTIC_CACHE_ENABLED` loads embedding model in-process (~400MB RAM); may return stale answers for paraphrased queries |
| **Compose DB starts empty** | Run migrate + PDF ingest after first `docker compose up` |
| **No FX conversion** | USD and INR coexist; cross-market rankings are explicitly flagged, not converted |
| **RAG corpus is static PDFs** | Filings must be re-ingested manually; no live SEC EDGAR pull |
| **Ingestion on FastAPI only** | Streamlit UI does not start the scheduler; Space entrypoint starts API for live bars |
| **LLM provider dependency** | Groq/Tavily/Pinecone keys required for full demo; offline modes are partial |
| **Mock vs real load tests** | `MOCK_MODE=1` + `load_test.py --mode infra` measures routing/DB/cache/rate limits **without** real LLM latency; run `--mode smoke` with mock off at low concurrency for true end-to-end timing |
| **SQL repair multi-statement edge case** | Repair retries occasionally returned two `SELECT`s separated by blank lines (Postgres rejected as syntax error); fixed via `_normalize_sql()` extracting a single statement—found during load testing |
| **Multi-hop LLM latency** | SQL/HYBRID routes can chain **3–4 sequential LLM calls** (router → SQL gen → synthesis, etc.); with `openai/gpt-oss-20b` expect multi-second end-to-end—characteristic of the pipeline, not a bug; future work: parallelize independent hops or use a faster/larger model where quota allows |
| **`llama-3.1-8b-instant` retirement** | Groq is shutting this model down **2026-08-16**. Set `GROQ_MODEL=openai/gpt-oss-20b` (the `.env.example` default) in every deployed `.env`/Space secret before that date or `LLM_PROVIDER=groq` calls will start failing |

**Roadmap:** incremental Pinecone upsert (no full re-index), SEC/EDGAR auto-fetch, FX-normalized analytics view, Prometheus metrics export.

---

## Project Structure

```
smra/
├── app.py / ui.py          # Streamlit chat UI
├── api.py                  # FastAPI (/query, /health, /audit)
├── router.py                # Intent classification
├── orchestrator.py         # HYBRID synthesis
├── agents/                 # sql_agent, rag_agent, web_agent
├── ingestion/               # scheduler, upsert (Postgres)
├── data_sources/            # yfinance adapter
├── config/tickers.py        # 50 US + NSE symbols
├── db/                      # Postgres schema, migrations/, migrate.py runner
├── scripts/                 # ingest_pdfs, migrate_sqlite_to_postgres, load_test.py, start_space.sh
├── eval/                    # golden dataset, LLM judge
├── utils/                   # db, security, guardrails, observability, currency, warmup
└── pdfs/                    # 8 company filings
tests/                       # pytest suite (86 tests)
.github/
├── workflows/ci.yml         # lint + test matrix + secret-scan + docker-build + offline evals
├── dependabot.yml           # pip / github-actions / docker updates
├── CODEOWNERS, PULL_REQUEST_TEMPLATE.md, ISSUE_TEMPLATE/
.pre-commit-config.yaml      # ruff + gitleaks + hygiene hooks
CHANGELOG.md                 # Keep a Changelog format
docker-compose.yml           # Postgres + Redis + FastAPI
Dockerfile                   # HF Spaces / local image (non-root, CPU torch, dual entrypoint)
```

---

## API Reference (FastAPI)

```bash
# Health
curl http://localhost:8010/health

# Query (auth optional when AUTH_ENABLED=0)
curl -X POST http://localhost:8010/query \
  -H "Content-Type: application/json" \
  -d '{"query": "What was Apple total net sales in the 10-K?"}'

# Recent audit entries
curl http://localhost:8010/audit?limit=10
```

Enable auth: `AUTH_ENABLED=1` + `SMRA_API_KEYS=key1,key2` → pass `-H "X-API-Key: key1"`.

---

## References

- [OWASP LLM Top 10](https://genai.owasp.org/llm-top-10/)
- [FinRobot](https://github.com/AI4Finance-Foundation/FinRobot) · [FinGPT](https://github.com/AI4Finance-Foundation/FinGPT)

---

## License & Disclaimer

MIT License. **Not financial advice.** For education and research only—consult a licensed advisor before making investment decisions.
