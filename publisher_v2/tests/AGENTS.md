# Test Suite

## TDD is the default workflow

- Write tests **before** implementation. Tests codify the expected behavior from specs.
- TDD cycle: write a failing test -> write minimal code to pass -> refactor.

## When tests fail

- **Never blindly adjust tests to pass.** Investigate the root cause first.
- Check the spec in `docs_v2/` — if the test matches the spec, fix the code.
- Only update a test when the test itself is genuinely wrong.

## Framework

- `pytest` + `pytest-asyncio` (async mode `auto`).
- `pythonpath` is `publisher_v2/src` — import as `from publisher_v2.xxx import yyy`.
- Async tests work without decorators thanks to `asyncio_mode = "auto"`.
- Mock external services (Dropbox, OpenAI, Telegram) — never call real APIs in tests.
- Run: `uv run pytest -v --tb=short` or `make test` for coverage.
