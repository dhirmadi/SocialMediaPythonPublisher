---
description: Run tests, optionally filtered by pattern
allowed-tools: Bash, Read
---

Run the test suite. If $ARGUMENTS is provided, use it as a pytest filter expression:

- No arguments: `uv run pytest -v --tb=short`
- With arguments: `uv run pytest -v --tb=short -k "$ARGUMENTS"`

Report pass/fail counts and any failures with the relevant traceback.
