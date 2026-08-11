# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- `/health/ready` endpoint: real readiness probe that pings Postgres (`SELECT 1`) and Redis,
  returning `503` on a hard Postgres failure — `/health` stays a cheap liveness-only check
- `pip-audit` dependency vulnerability scan added to CI (report-only for now)

### Known issues surfaced this pass (not yet fixed, documented in README Known Limitations)
- `pip-audit` currently flags real CVEs in transitive deps (`pypdf`, `pillow`, `aiohttp`,
  `langchain-core`, `langchain-text-splitters`, `transformers`) whose fixes require untested
  major-version bumps — deferred to a dedicated upgrade pass rather than bumped blind
- No static type checking (`mypy` takes 15+ min on this codebase and there's no type-hint
  discipline yet) — deliberately not added as a CI gate
- No hash-pinned dependency lockfile

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
