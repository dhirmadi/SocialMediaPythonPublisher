# PUB-043 — Orchestrator runtime: accept publisher type `email`: Implementation Summary

**Status:** Done (archived)
**Date:** 2026-05-05

## Files Changed

- `publisher_v2/src/publisher_v2/config/source.py` — extended FetLife-style email branch in `_build_app_config_v2` so the same code path runs when `p.type` is either `"fetlife"` or `"email"`.
- `publisher_v2/tests/config/test_orchestrator_runtime_config.py` — added 3 new tests + parametrized AC3 cases; tightened existing `test_parses_schema_v2` to assert `credentials_refs["smtp"] == "smtp-ref"`.

## Acceptance Criteria

- [x] **AC1** — Publisher type `"email"` enables `platforms.email_enabled`, populates `EmailConfig`, and registers `credentials_refs["smtp"]` (test: `test_publisher_type_email_enables_email_with_smtp_ref`).
- [x] **AC2** — Existing `"fetlife"` payload still produces `email_enabled=True` and `credentials_refs["smtp"]` set (test: tightened `test_parses_schema_v2`).
- [x] **AC3** — Type `"email"` with missing/blank `recipient`, blank `from_email`, or `password_ref=None` ⇒ `email_enabled=False`, no `smtp` credentials_ref (test: `test_publisher_type_email_disabled_when_required_field_missing` parametrized over the three cases).
- [x] **AC4** — Type `"email"` with `email_server` absent ⇒ `email_enabled=False`, no crash (test: `test_publisher_type_email_disabled_when_email_server_missing`).

## Test Results

```
publisher_v2/tests/config/test_orchestrator_runtime_config.py — 8 passed
Full suite: 964 passed, 127 warnings in 57.80s
```

## Quality Gates

| Gate | Result |
|------|--------|
| Format (`ruff format`) | OK (172 files unchanged) |
| Lint (`ruff check`) | All checks passed |
| Type check (`mypy`) | No new errors in touched files (pre-existing errors in `test_analysis_context.py`, `test_alt_text.py`, `scripts/vision_token_benchmark.py` only) |
| Tests | 964 passed, 0 failed |
| Coverage — `config/source.py` | 81% (≥80% gate) |
| Coverage — overall | 89% (≥85% gate) |

## Notes

- Implementation followed the spec's "Prefer a named constant or tuple" guidance with an inline `p.type in ("fetlife", "email")` check next to the existing branch (no other tuple constant was already in use for this).
- `from_email` is required as a non-empty `str` by `OrchestratorEmailServer`, so AC3's "missing `from_email`" case is exercised with an empty string `""` (matches the existing falsy check `if recipient and cfg.email_server.from_email:` and is the closest payload shape that still passes pydantic validation — a truly absent field would be a separate model-level validation failure already covered by orchestrator-side validation).
- Preview mode is unaffected (config-layer change only).
- No secrets introduced; the test fixture's `"smtp-ref"` is an opaque ref string (suppressed `S107` with a targeted `noqa` and explanatory comment).
