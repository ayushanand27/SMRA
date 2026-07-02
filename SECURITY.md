# Security Policy

## Reporting a vulnerability

Please open a private security advisory on GitHub or email the maintainer.
Do not file public issues for security problems.

## Threat model & controls

SMRA is an LLM application and follows the
[OWASP Top 10 for LLM Applications](https://genai.owasp.org/llm-top-10/).

| Risk | Control in SMRA |
|------|-----------------|
| LLM01 Prompt Injection | Deterministic input guardrails (`smra/utils/guardrails.py`) reject known override/jailbreak patterns before any model call. |
| LLM02 Insecure Output Handling | Model output is HTML/script-sanitized before rendering. SQL is restricted to `SELECT` and executed with parameterized fallbacks. |
| LLM06 Sensitive Info Disclosure | Secrets live only in `smra/.env` (git-ignored). Raw provider errors are not surfaced verbatim to users. |
| LLM08 Excessive Agency | Agents are read-only: SQL is `SELECT`-only, no write path to the DB, tools are limited to search/retrieval. |
| LLM09 Overreliance | Every response carries a "not financial advice" disclaimer; RAG shows sources and confidence. |
| LLM10 Unbounded Consumption | Input length limits + provider-side retry/backoff; API-key auth and per-identity rate limiting (`smra/utils/security.py`); LLM calls are tracked for latency and cost. |

## API authentication & rate limiting

The FastAPI service (`smra/api.py`) supports optional controls, off by default for
local dev and enabled via environment variables:

- **API-key auth** — set `AUTH_ENABLED=1` and `SMRA_API_KEYS=key1,key2`. Protected
  endpoints (`/query`, `/audit`) require the `X-API-Key` header. Keys are compared
  in constant time; if auth is enabled with no keys configured, requests fail closed.
- **Rate limiting** — `RATE_LIMIT_ENABLED=1` (default) with `RATE_LIMIT_PER_MIN`
  applies a sliding-window limit per API key (or client IP when unauthenticated).
  Over-limit requests return `429` with a `Retry-After` header. The store is
  process-local; use Redis for multi-instance deployments.
- **Streamlit UI gate** — set `UI_PASSWORD` to require a shared password before the
  UI is usable (constant-time comparison).

## Operational notes

- Rotate API keys periodically; never log full prompts containing secrets.
- Enable `JSON_LOGS=1` in production for structured, aggregatable logs.
- Optional managed tracing via Langfuse (`LANGFUSE_ENABLED=1` + keys). Traces
  degrade to a no-op if the SDK/keys are absent, so the app never breaks.
- Guardrails are a first layer, not a complete defense. For regulated
  deployments add an ML-based prompt-injection classifier and PII redaction.
