---
description: "Test authoring conventions, TDD workflow, and failing-test diagnostic rules"
paths:
  - "publisher_v2/tests/**"
---

# Testing conventions

## TDD workflow
- **Write tests before implementation.** Tests are the executable specification.
- TDD cycle: failing test -> minimal passing code -> refactor.
- Every new feature or bug fix starts with a test that captures the expected behavior.

## When tests fail (critical)
- **Never blindly adjust tests to make them pass.**
- A failing test is a diagnostic signal. Investigate before changing anything.
- Read the relevant spec in `docs_v2/` to understand intended behavior.
- If the test correctly asserts the spec'd behavior: **fix the code, not the test**.
- Only update a test when the test itself is genuinely wrong (incorrect assertion, stale mock, changed spec).
- When updating a test, explain *why* the old assertion was wrong and what the correct behavior is.

## Framework & conventions
- Framework: `pytest` + `pytest-asyncio` (async mode `auto`).
- Test root: `publisher_v2/tests/`. `pythonpath` is `publisher_v2/src`.
- Import pattern: `from publisher_v2.xxx import yyy`.
- Name files `test_<module>.py`, classes `Test<Feature>`, functions `test_<behavior>`.
- Focus on high-signal tests: happy path + key error branches. Avoid testing framework internals.
- Use `unittest.mock.patch` / `pytest.monkeypatch` for external dependencies (Dropbox, OpenAI, Telegram).
- Async tests need no special decorator — `asyncio_mode = "auto"` handles it.
- Run before committing: `uv run pytest -v --tb=short`.
