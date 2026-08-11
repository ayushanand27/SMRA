# Changelog

All notable changes to this project are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
