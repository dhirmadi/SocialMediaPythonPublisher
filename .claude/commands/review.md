---
description: Review staged or recent changes for quality, security, style, and spec compliance
allowed-tools: Bash, Read
---

Review the current changes in the working tree:

1. Run `git diff --stat` to identify changed files.
2. Run `git diff` to see the full diff.
3. For each changed file, check:
   - **Spec compliance**: does the implementation match the relevant spec in `docs_v2/08_Epics/` or `docs_v2/08_Features/`?
   - **TDD**: do new behaviors have corresponding tests? Were tests written/updated alongside code?
   - **Test integrity**: were any existing tests modified? If so, verify the test change is justified by a spec change — not just adjusted to pass.
   - Ruff lint compliance (run `uv run ruff check` on changed files)
   - Security: no hardcoded secrets, tokens, or API keys
   - Type annotations on public functions
   - Async hygiene: no blocking calls in async functions without `asyncio.to_thread()`
   - Backward compatibility: CLI flags, endpoint contracts, config semantics preserved
4. Report findings as a structured list: file, issue, severity (error/warning/info), suggestion.
