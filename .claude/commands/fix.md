---
description: Auto-fix lint and formatting issues
allowed-tools: Bash, Read, Write
---

Fix all auto-fixable issues:

1. Run `uv run ruff format .` to format code.
2. Run `uv run ruff check --fix .` to auto-fix lint issues.
3. Run `uv run ruff check .` to verify no remaining violations.
4. If violations remain, report them and suggest manual fixes.
