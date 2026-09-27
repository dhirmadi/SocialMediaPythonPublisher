# PUB-084 — DRY Review Standalone Batch: Implementation Summary

**Status:** In Progress (wave 1 of 5 complete)
**Date:** 2026-09-27

One section per wave; each wave ships as its own PR.

## Wave 1 — Posted-state isolation (#296) and Instagram tenant option (#273)

### Files Changed

- `publisher_v2/src/publisher_v2/services/publishers/instagram.py` — `INSTAGRAM_SESSION_KEY = "default"` module constant; `tenant` constructor parameter and `self._tenant` removed; all 12 session-store calls use the constant; docstrings state the single-instance-per-database limit. `session_store` seam kept.
- `publisher_v2/src/publisher_v2/services/instagram_session.py` — docstrings only ("one row per key", single-instance note). Store method signatures unchanged; no schema change.
- `docs_v2/05_Configuration/CONFIGURATION.md` — "Instagram: one instance per database (#273)" note after the platform-secrets table in §1 (the document has no Instagram section of its own).
- `publisher_v2/tests/conftest.py` — autouse `_isolate_env` sets `XDG_CACHE_HOME` to `tmp_path_factory.mktemp("xdg-cache")` per test; `bypass_dedup` fixture deleted.
- `publisher_v2/tests/test_suite_hygiene.py` — new: AC1/AC2 ratchets.
- Deleted from 8 test files: seven `_isolated_posted_state` autouse fixtures and `_reset_cache` in `test_utils_support.py`.
- Deleted from 9 test files: 17 inline `setenv("XDG_CACHE_HOME", ...)` lines.
- Deleted from 7 test files: 42 isolation-only `load_posted_*`/`save_posted_*` no-op patches (behavioural patches in `test_workflow_metadata_selection.py` kept).
- `test_publishers_platforms.py` — six Instagram session-location tests now read the autouse `XDG_CACHE_HOME` instead of setting their own (assertions unchanged); `_SpyStore` records `(method, key)`; AC3 tests added.
- `test_utils_support.py` — two state tests rooted at the autouse `XDG_CACHE_HOME` (assertions unchanged).
- `test_storage_ops_metering_wiring.py` — `bypass_dedup` parameter removed from two tests.

Net: 28 files, +154 / −166 lines.

### Acceptance Criteria

- [x] AC1 — each test gets its own empty `XDG_CACHE_HOME` under pytest's temp dir (test: `test_posted_state_cache_is_isolated_per_test`, parametrised `[first]`/`[second]` to prove per-test; mutation-tested against a shared dir)
- [x] AC2 — no per-file `XDG_CACHE_HOME`, no `bypass_dedup`, no no-op posted-state patches (test: `test_no_per_file_posted_state_isolation`)
- [x] AC3 — no `tenant` parameter; one module-level session key (tests: `test_instagram_publisher_takes_no_tenant_argument`, `test_instagram_session_store_uses_one_key`, plus `test_instagram_relogin_uses_one_key` — an extra test, not in the handoff table, covering the relogin `clear`/`save` and back-off `set_blocked_until` path at the reviewer's request)

Manual check: running the eight previously unisolated files left `~/.cache/publisher_v2/posted.json` unchanged (same mtime and size).

### Test Results

1970 passed, 2 skipped, 0 failed under three random seeds (3349438808, 2300993560, 1113728778). Baseline before the wave: 1964 passed, 2 skipped.

### Quality Gates

- Format: ✅ (`ruff format --check .`, 261 files)
- Lint: ✅ (`ruff check .`)
- Type check: ✅ (`mypy`, 65 files, no issues)
- Tests: 1970 passed, 0 failed
- Coverage: 93.56% overall; `publishers/instagram.py` 99%, `instagram_session.py` 83%

### Subagent Verdicts

- `code-reviewer`: BLOCKED (resolved) → PASS WITH NITS. The first review found the "inline posted-hash patches that exist only for isolation" scope bullet not done; the test-engineer deleted the 42 patches and extended the AC2 guard. The remaining nit (six stale "Bypass dedup state" comments) was removed by the Lead as a comment-only edit.
- `security-auditor`: N/A — no change to `web/`, auth, secrets or config loading; Instagram session encryption unchanged.

### Linked Issues

- #296 — closed by the wave 1 PR (`Closes #296`)
- #273 — closed by the wave 1 PR (`Closes #273`)

### Notes

- Role split: #296 is test infrastructure only, so the test-engineer did both the red tests and the conftest/fixture changes; the developer (which never edits tests) did #273's source change.
- Lead decision: the six Instagram session-location tests were rewritten to read the autouse cache dir rather than allowlisted in the AC2 guard.
- The AC2 guard catches `setattr(..., lambda: set()|None)` forms only; `patch(..., return_value=set())` is not covered (none exist today).
