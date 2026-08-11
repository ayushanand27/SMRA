# Contributing to SMRA

Thanks for your interest in improving the Stock Market Research Assistant.

## Development setup

Use a **project-local virtual environment** — installing into a shared/global Python breaks
this project when some other project's install pulls in an incompatible transitive dependency
(this has actually happened: a global `starlette` upgrade unrelated to SMRA crashed the API on
startup with a FastAPI/Starlette version mismatch).

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows;  source .venv/bin/activate on macOS/Linux
python -m pip install -r smra/requirements.txt
python -m pip install -r smra/requirements-dev.txt
cp smra/.env.example smra/.env   # then add your keys
pre-commit install               # runs ruff + gitleaks + hygiene checks on every commit
```

## Before opening a PR

Run the full local quality gate:

```bash
ruff check smra tests                                    # lint
pytest --cov=smra --cov-report=term-missing               # unit tests + coverage (floor: 35%)
python -m smra.eval.run_eval --threshold 0.7               # offline routing/guardrail evals
```

CI (`.github/workflows/ci.yml`) runs lint + tests (Python 3.10/3.11/3.12) + a Gitleaks secret
scan + a Docker build check on every PR and must be green.

## Guidelines

- Keep agent responses on the shared schema (`smra/utils/schemas.py`): use
  `success_response()` / `error_response()`.
- All user input must pass through `smra/utils/guardrails.check_input`.
- Route LLM calls through `smra/utils/llm.call_llm` so observability and retries apply.
- Add or update a golden case in `smra/eval/golden_dataset.json` when you change routing behavior.
- No secrets in code or tests. Never commit `smra/.env`.

## Commit style

Use conventional prefixes where possible: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`.
