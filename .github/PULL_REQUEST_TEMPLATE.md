## Summary

<!-- What does this PR change, and why? -->

## Test plan

- [ ] `ruff check smra tests`
- [ ] `pytest`
- [ ] `python -m smra.eval.run_eval --threshold 0.7`
- [ ] Manually exercised the affected route(s) (Streamlit UI / `/query` / `/health`)

## Checklist

- [ ] No secrets, API keys, or connection strings in the diff (`.env` files are git-ignored — double check `git diff --stat`)
- [ ] Docs (`README.md`, `.env.example`) updated if behavior or config changed
