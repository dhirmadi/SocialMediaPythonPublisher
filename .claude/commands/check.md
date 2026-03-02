---
description: Run all quality checks (format, lint, type-check, test)
allowed-tools: Bash, Read
---

Run the full quality pipeline. Execute each step sequentially and report results:

1. Format: `uv run ruff format .`
2. Lint fix: `uv run ruff check --fix .`
3. Lint (verify clean): `uv run ruff check .`
4. Type check: `uv run mypy . --ignore-missing-imports --exclude=venv --exclude=env`
5. Tests: `uv run pytest -v --tb=short`

If any step fails, stop and report the issue with actionable fix suggestions. Summarize results at the end.
