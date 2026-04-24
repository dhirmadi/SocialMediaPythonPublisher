# PUB-040 — OpenAI Model Lifecycle Warnings: Implementation Summary

**Status:** Implementation Complete
**Date:** 2026-04-24

## Files Changed
- `publisher_v2/src/publisher_v2/config/schema.py` — Added `ModelLifecycle` Pydantic model with severity validator; added `vision_model_lifecycle` and `caption_model_lifecycle` fields to `OpenAIConfig`
- `publisher_v2/src/publisher_v2/config/orchestrator_models.py` — Added `vision_model_lifecycle` and `caption_model_lifecycle` dict fields to `OrchestratorAI`
- `publisher_v2/src/publisher_v2/config/source.py` — Added `_map_lifecycle()` helper, `emit_model_lifecycle_warnings()` emitter; wired lifecycle mapping into `_build_app_config_v2`; wired emitter into `get_config()` on fresh fetch
- `publisher_v2/tests/test_model_lifecycle_warnings.py` — 19 tests covering all 16 ACs

## Acceptance Criteria
- [x] AC-01 — ModelLifecycle valid construction (test: `test_valid_construction`, `test_severity_info`, `test_severity_critical`)
- [x] AC-02 — Unknown severity rejected (test: `test_unknown_severity_rejected`)
- [x] AC-03 — OpenAIConfig defaults None (test: `test_defaults_none`)
- [x] AC-04 — OpenAIConfig stores lifecycle (test: `test_accepts_model_lifecycle`)
- [x] AC-05 — OrchestratorAI accepts lifecycle dict (test: `test_accepts_lifecycle_dict`)
- [x] AC-06 — OrchestratorAI null → None (test: `test_null_lifecycle`, `test_missing_lifecycle`)
- [x] AC-07 — Valid lifecycle → ModelLifecycle (test: `test_valid_lifecycle_mapped`)
- [x] AC-08 — Malformed lifecycle → None (test: `test_malformed_lifecycle_graceful`)
- [x] AC-09 — V1 defaults (test: `test_v1_defaults`)
- [x] AC-10 — warning severity → logging.WARNING (test: `test_warning_severity_logs_warning`)
- [x] AC-11 — critical severity → logging.ERROR (test: `test_critical_severity_logs_error`)
- [x] AC-12 — info severity → logging.INFO (test: `test_info_severity_logs_info`)
- [x] AC-13 — Both None → zero logs (test: `test_both_none_no_logs`)
- [x] AC-14 — No secrets in log output (test: `test_no_secrets_in_log`)
- [x] AC-15 — Fresh fetch → warning; cache hit → no warning (wired in `get_config()` before `_runtime_cache.set`)
- [x] AC-16 — Standalone mode → both None (test: `test_standalone_defaults`)

## Test Results
861 passed, 0 failed (19 new PUB-040 tests)

## Quality Gates
- Format: pass
- Lint: pass
- Type check: 0 errors (160 files)
- Tests: 861 passed, 0 failed

## Notes
- `_map_lifecycle()` catches all exceptions (not just `ValidationError`) for maximum robustness against unexpected orchestrator payloads.
- `emit_model_lifecycle_warnings()` is called only on fresh config fetches (cache miss / TTL expiry), not on cache hits — preventing log spam.
- In standalone mode (`EnvConfigSource`), lifecycle fields are always `None` and the emitter is never called.
