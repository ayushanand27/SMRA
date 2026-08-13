# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.4.0] - 2026-08-14

### Added
- **MCP server** (`smra/mcp_server.py`): exposes SMRA as a tool for any MCP-capable AI agent
  (Claude Desktop, Claude Code) via the `ask_smra` tool, over stdio. Verified against the real
  protocol, not just unit-tested: spawned it as a subprocess, listed tools and called `ask_smra`
  through the official `mcp` client SDK, got back a correct routed answer end-to-end through
  Groq + Postgres.
- **`smra/orchestrator.py: answer_query()`** — refactored the query pipeline (guardrails →
  contextualize → cache → route → agents → synthesize → cache-write → audit) out of
  `smra/api.py` into one shared function. Before this, that logic was duplicated between
  `api.py`'s `/query` handler and `app.py`'s Streamlit chat handler (and would have been
  triplicated again by the MCP server). Now the FastAPI endpoint and the MCP server both call
  the same function, so neither can skip a safety or audit step by reimplementing the pipeline
  slightly differently. Verified live: an MCP tool call and an API call both appear correctly
  in the same `/audit` trail.
- README: published the eval suite's actual measured numbers (100% routing accuracy, 14/14,
  with the per-category breakdown) instead of just claiming test coverage exists.
- **Deterministic financial calculations** (`smra/utils/financial_calc.py`): moving averages,
  % return, CAGR, annualized volatility, and 52-week high/low are computed in pure Python from
  the SQL agent's full result set, never estimated by the LLM. Handles multi-symbol results
  (per-symbol computation, not a meaningless blended average across different stocks). Two real
  bugs found and fixed via live end-to-end testing against ground truth (not just unit tests):
  (1) the LLM sometimes wrote `AVG(close) GROUP BY date` for "moving average" questions, which
  is mathematically a no-op per row, not a rolling average — SQL_SYSTEM now explicitly forbids
  aggregating for these query types and requires plain per-date rows instead; (2) the SQL used
  ascending `ORDER BY date LIMIT N`, fetching the *oldest* N rows instead of the most recent —
  fixed to require `DESC` when the user doesn't give an explicit date range. Verified after both
  fixes: NVDA's 20-day moving average from the API matched a value independently computed
  straight from the database, to the cent ($795.41).
- **Multi-turn conversation memory** (`smra/utils/conversation.py`): follow-up questions are
  resolved into standalone questions using recent chat history before routing. Stateless —
  the client (Streamlit session, or an API caller's `history` array on `/query`) owns history,
  not the server. No-ops (zero extra latency) when there's no history. The resolved question
  is surfaced back via `resolved_query` in the API response / "Interpreted as: …" in the UI;
  the audit trail keeps the original question the user actually typed. Verified live:
  "What about NVIDIA revenue instead?" (with a prior Apple-10-K exchange in history) correctly
  resolved to "What was NVIDIA revenue in their 10-K?" and returned a grounded, cited answer.
- `/health/ready` endpoint: real readiness probe that pings Postgres (`SELECT 1`) and Redis,
  returning `503` on a hard Postgres failure — `/health` stays a cheap liveness-only check
- `pip-audit` dependency vulnerability scan added to CI (report-only for now)

### Security
- Bumped `pypdf` `<6.0.0` → `<7.0.0` (6.15.0), clearing ~24 CVEs. Verified via full test suite
  and a live RAG query (`apple.pdf` citation, correct figures) since `pypdf` isn't covered by
  any unit test directly — only used in `smra/scripts/ingest_pdfs.py`

### Known issues surfaced this pass (not yet fixed, documented in README Known Limitations)
- Attempted `pillow`, `aiohttp`, and `transformers`/`sentence-transformers` CVE fixes too; all
  three broke something real on testing and were reverted:
  - `pillow≥12` conflicts with `streamlit==1.41.1` (`pillow<12` required)
  - `transformers 5.x`/`sentence-transformers 5.x` fail to *import* at runtime here (`tokenizers`
    ABI mismatch) despite pip reporting no conflict — caught 2 semantic-cache test failures
  - `aiohttp≥3.11` forces `langchain-pinecone≥0.2.7` → drags `langchain-core` to the `1.x` line,
    breaking `langchain`/`langchain-community`/`langchain-huggingface`/`langgraph` (pinned
    `<1.0.0`); the CVE fixes for `langchain-core`/`langchain-text-splitters` only exist in that
    `1.x` line, so this needs a full LangChain 1.0 migration, not a version bump
- No static type checking (`mypy` takes 15+ min on this codebase and there's no type-hint
  discipline yet) — deliberately not added as a CI gate
- No hash-pinned dependency lockfile — a same-machine attempt hit a Windows 260-char path limit
  creating a venv, and a plain `pip freeze` on the shared global env pulled in ~400 unrelated
  packages; needs a clean environment (shorter path or Linux/WSL), good candidate for a CI job

### Fixed
- Local dev environment had a `starlette 1.6.0` / `fastapi 0.115.6` version mismatch (installed
  outside this project's control, via a shared global Python environment) that crashed the API
  on startup with `TypeError: Router.__init__() got an unexpected keyword argument 'on_startup'`;
  pinned `starlette` back to a compatible `<0.42` version. Root cause — no project-local virtual
  environment — is unresolved; see README.

## [0.3.0] - 2026-08-11

### Security
- Stopped tracking `smra/.env.backup-before-invalid-key-test`, which contained live-looking
  credentials, and purged it from git history entirely (`git filter-repo`)
- Hardened `.gitignore` to block every `.env*` variant except `*.env.example`, plus all
  `*.db`/`*.sqlite*` binaries and common IDE cruft
- Added CORS policy + baseline security headers (`X-Content-Type-Options`, `X-Frame-Options`,
  `Referrer-Policy`, `Strict-Transport-Security`) to the FastAPI service
- Added `ENV=production` startup gate: the API now refuses to boot with auth/rate-limiting
  disabled when explicitly marked production
- Docker image now runs as an unprivileged `appuser` instead of root
- Added Gitleaks secret scanning to CI and as a pre-commit hook

### Fixed
- SQL agent prompt now accounts for Postgres's strict `GROUP BY` rules, fixing queries like
  "latest closing price of X" that previously failed with a `GroupingError`

### Added
- `smra/db/migrate.py`: tracked, idempotent migration runner (`schema_migrations` table)
  covering the baseline schema plus `smra/db/migrations/*.sql`
- Dependabot config for pip, GitHub Actions, and Docker base images
- CI: Python 3.10/3.11/3.12 matrix, coverage floor (`pytest-cov`, currently 35%), and a
  Docker build check
- CODEOWNERS, PR template, and issue templates
- Groq LLM calls now fail over to Gemini (when `GEMINI_API_KEY` is set) instead of hard-failing

### Changed
- README: added secrets-hygiene guidance and flagged the `llama-3.1-8b-instant` retirement
  (2026-08-16)

## [0.2.0] - prior to this changelog

Baseline established by commit history: multi-agent routing (SQL/RAG/WEB/HYBRID), Postgres +
live yfinance ingestion, Pinecone RAG over 8 filings, Redis rate limiting, API-key auth,
Langfuse tracing, semantic cache, Docker Compose stack. See `git log` for details predating
this file.
