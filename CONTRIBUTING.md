# Contributing to SMRA

Thanks for your interest in improving the Stock Market Research Assistant.

## Development setup

```bash
python -m pip install -r smra/requirements.txt
python -m pip install -r smra/requirements-dev.txt
cp smra/.env.example smra/.env   # then add your keys
```

## Before opening a PR

Run the full local quality gate:

```bash
ruff check smra tests          # lint
pytest                         # unit tests
python -m smra.eval.run_eval   # offline routing/guardrail evals
```

CI (`.github/workflows/ci.yml`) runs lint + tests on every PR and must be green.

## Guidelines

- Keep agent responses on the shared schema (`smra/utils/schemas.py`): use
  `success_response()` / `error_response()`.
- All user input must pass through `smra/utils/guardrails.check_input`.
- Route LLM calls through `smra/utils/llm.call_llm` so observability and retries apply.
- Add or update a golden case in `smra/eval/golden_dataset.json` when you change routing behavior.
- No secrets in code or tests. Never commit `smra/.env`.

## Commit style

Use conventional prefixes where possible: `feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `chore:`.
