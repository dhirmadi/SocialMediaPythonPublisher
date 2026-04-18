# PUB-034 — Usage Metering: Implementation Summary

**Status:** Implementation Complete
**Date:** 2026-04-18

## Files Changed

### New files
- `publisher_v2/src/publisher_v2/services/usage_meter.py` — `UsageMeter` class with fire-and-forget `emit()` / `emit_all()`
- `publisher_v2/tests/config/test_orchestrator_usage.py` — Tests for `post_usage()` and `orchestrator_client` property (8 tests)
- `publisher_v2/tests/test_ai_usage.py` — Tests for `AIUsage` dataclass and AI method tuple returns (9 tests)
- `publisher_v2/tests/test_usage_meter.py` — Tests for `UsageMeter.emit()` / `emit_all()` (6 tests)

### Modified files
- `publisher_v2/src/publisher_v2/core/exceptions.py` — Added `UsageMeteringError`, `InsufficientBalanceError`
- `publisher_v2/src/publisher_v2/core/models.py` — Added `AIUsage` dataclass
- `publisher_v2/src/publisher_v2/config/orchestrator_client.py` — Added `post_usage()` method; updated `resolve_credentials` 403 handler for balance disambiguation
- `publisher_v2/src/publisher_v2/config/source.py` — Added `orchestrator_client` property to `OrchestratorConfigSource` and `EnvConfigSource`; added to `ConfigSource` protocol
- `publisher_v2/src/publisher_v2/services/ai.py` — Changed all 5 low-level AI methods to return `(result, AIUsage | None)` tuples; updated `AIService` to aggregate and return `list[AIUsage]`; added `_extract_usage()` helper
- `publisher_v2/src/publisher_v2/core/workflow.py` — Added optional `usage_meter` parameter; emit usage after vision analysis and caption generation
- `publisher_v2/src/publisher_v2/web/service.py` — Construct `UsageMeter` in orchestrated mode; emit usage in `analyze_and_caption()`; pass meter to `WorkflowOrchestrator`
- `publisher_v2/tests/config/test_orchestrator_credentials.py` — Added 403 disambiguation tests (4 tests)
- 16 existing test files updated to handle new tuple return signatures from AI methods

## Acceptance Criteria

### Part A — `OrchestratorClient.post_usage()`
- [x] AC-A1 — POST /v1/billing/usage with JSON body and Bearer header (test: `test_post_usage_sends_correct_request`)
- [x] AC-A2 — 200 returns parsed JSON (test: `test_post_usage_200_returns_dict`)
- [x] AC-A3 — Duplicate idempotency key treated as success (test: `test_post_usage_duplicate_idempotency_key_success`)
- [x] AC-A4 — 422 raises UsageMeteringError with metric name (test: `test_post_usage_422_raises_usage_metering_error`)
- [x] AC-A5 — 403 raises CredentialResolutionError (test: `test_post_usage_403_raises_credential_resolution_error`)
- [x] AC-A6 — 404 raises UsageMeteringError (test: `test_post_usage_404_raises_usage_metering_error`)
- [x] AC-A7 — 5xx after retries raises OrchestratorUnavailableError (test: `test_post_usage_5xx_raises_orchestrator_unavailable`)

### Part B — AIUsage dataclass + AI method returns
- [x] AC-B1 — AIUsage dataclass with correct fields (test: `test_ai_usage_dataclass_fields`)
- [x] AC-B2 — VisionAnalyzerOpenAI.analyze() returns tuple (test: `test_vision_analyzer_returns_usage_tuple`)
- [x] AC-B3 — All CaptionGenerator methods return tuples (tests: `test_caption_generator_generate*`)
- [x] AC-B4 — None usage handled gracefully (test: `test_vision_analyzer_none_usage`)
- [x] AC-B5 — AIService aggregates usage lists (test: `test_ai_service_create_caption_pair_from_analysis_returns_usage_list`)
- [x] AC-B6 — NullAIService safe (test: `test_null_ai_service_has_no_crash_attributes`)
- [x] AC-B7 — Existing callers updated (verified via 679 passing tests)

### Part C — UsageMeter + integration
- [x] AC-C1 — UsageMeter with emit/emit_all (test: `test_usage_meter_has_emit_and_emit_all`)
- [x] AC-C2 — emit() calls post_usage correctly (test: `test_emit_calls_post_usage_with_correct_args`)
- [x] AC-C3 — Exceptions swallowed and logged (test: `test_emit_swallows_exception_and_logs`)
- [x] AC-C4 — emit_all skips None/zero entries (test: `test_emit_all_skips_none_and_zero_tokens`)
- [x] AC-C5 — WebImageService.analyze_and_caption emits usage (integrated in service.py)
- [x] AC-C6 — WorkflowOrchestrator.execute emits usage (integrated in workflow.py)
- [x] AC-C7 — Standalone mode: usage_meter is None (test: `test_standalone_mode_no_meter`)
- [x] AC-C8 — OrchestratorConfigSource exposes orchestrator_client (test: `test_orchestrator_config_source_exposes_client`)

### Part D — 403 disambiguation
- [x] AC-D1 — InsufficientBalanceError subclasses CredentialResolutionError (test: `test_insufficient_balance_error_is_subclass_of_credential_resolution_error`)
- [x] AC-D2 — 403 + insufficient_balance raises InsufficientBalanceError (test: `test_403_insufficient_balance_raises_insufficient_balance_error`)
- [x] AC-D3 — 403 + other codes raise CredentialResolutionError (tests: `test_403_forbidden*`, `test_403_unparseable*`)
- [x] AC-D4 — Subclass relationship verified (test: `test_insufficient_balance_error_is_subclass_of_credential_resolution_error`)

## Test Results

- 679 passed, 2 failed (pre-existing)
- 23 new tests added across 4 new test files
- 4 new tests added to existing test file
- Pre-existing failures: `test_email_publisher_sends_and_confirms` (email encoding), `test_admin_sections_hidden_for_non_admin` (HTML template)

## Quality Gates

- Format: Pass (ruff format)
- Lint: Pass (ruff check — 0 violations)
- Type check: Pass (mypy — 0 new errors; 3 pre-existing)
- Tests: 679 passed, 2 pre-existing failures
- Coverage: 88% overall; affected modules all >= 80%

## Notes

- AI method signature change has wide blast radius: 16 existing test files updated for tuple unpacking. All use the pattern `(result, usage)` for low-level methods and `(result, sd_caption, usages)` for AIService methods.
- `_extract_usage()` helper uses `getattr` for robustness with test doubles that may not have `usage` attribute.
- `UsageMeter` is constructed in `WebImageService.__init__` (not lazily) because tenant_id and client are available at that point.
- `WorkflowOrchestrator` receives `usage_meter` as an optional constructor parameter, keeping it decoupled from orchestrator details.
