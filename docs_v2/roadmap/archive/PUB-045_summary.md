# PUB-045 — R2 Storage Ops Metering: Implementation Summary

**Status:** Implementation Complete
**Date:** 2026-05-11

## Files Changed

- `publisher_v2/src/publisher_v2/services/managed_storage.py` — added thread-safe `_ops_count`/`_ops_lock`, `_count_ops()`, `drain_ops_count()`; inserted `_count_ops()` calls before each S3 API invocation (lists count per page).
- `publisher_v2/src/publisher_v2/services/storage_ops_meter.py` — new: `StorageOpsMeter` with `flush()` that drains the counter and POSTs `storage_ops_requests` to the orchestrator. Never raises.
- `publisher_v2/src/publisher_v2/config/schema.py` — added `storage_ops_metering_enabled: bool = False` to `FeaturesConfig`.
- `publisher_v2/src/publisher_v2/config/loader.py` — wired `FEATURE_STORAGE_OPS_METERING` (default false) via `parse_bool_env`.
- `publisher_v2/src/publisher_v2/config/orchestrator_models.py` — added `storage_ops_metering_enabled` to `OrchestratorFeatures` so runtime config can drive it.
- `publisher_v2/src/publisher_v2/web/service.py` — added `_init_storage_ops_meter()` (orchestrator mode + ManagedStorage + flag on → build meter); pass meter into `WorkflowOrchestrator`; `analyze_and_caption()` wraps `_analyze_and_caption_impl()` in try/finally to flush meter.
- `publisher_v2/src/publisher_v2/core/workflow.py` — added optional `storage_ops_meter` ctor param; `execute()` finally-block flushes meter (including preview mode).
- `publisher_v2/tests/test_managed_storage.py` — 17 new tests in `TestStorageOpsCounter` covering AC-A1..A8.
- `publisher_v2/tests/test_storage_ops_meter.py` — new file, 6 tests covering AC-B1..B6.
- `publisher_v2/tests/test_storage_ops_metering_wiring.py` — new file, 9 tests covering AC-C1..C7.

## Acceptance Criteria

### Part A — ManagedStorage counter
- [x] AC-A1 — `_ops_count` and `_ops_lock` init (test: `test_init_creates_ops_counter_and_lock`)
- [x] AC-A2 — atomic drain/reset (tests: `test_drain_ops_count_returns_and_resets`, `test_drain_ops_count_consecutive_calls`)
- [x] AC-A3 — increments per documented table (tests: `test_list_images_increments_counter_per_page`, `test_list_images_with_hashes_increments_counter_per_page`, `test_download_image_increments_counter`, `test_get_file_metadata_increments_counter`, `test_write_sidecar_increments_counter`, `test_archive_image_increments_counter_2_to_4`, `test_archive_image_counts_2_when_sidecar_copy_fails`, `test_move_image_increments_counter_2_to_4`, `test_delete_file_increments_counter_1_to_2`)
- [x] AC-A4 — presigned URL not counted (test: `test_get_temporary_link_does_not_increment_counter`)
- [x] AC-A5 — thumbnail not double-counted (test: `test_get_thumbnail_does_not_double_count`)
- [x] AC-A6 — 404 still counted (test: `test_download_sidecar_404_still_increments_counter`)
- [x] AC-A7 — thread-safe under concurrency (test: `test_counter_thread_safety_concurrent_increments`)
- [x] AC-A8 — retries counted (test: `test_retry_counts_each_attempt`)

### Part B — StorageOpsMeter
- [x] AC-B1 — class exists with flush (test: `test_storage_ops_meter_exists_with_flush_method`)
- [x] AC-B2 — correct POST args (test: `test_flush_calls_post_usage_with_correct_args`)
- [x] AC-B3 — hourly idempotency key (test: `test_idempotency_key_format_hourly_window`)
- [x] AC-B4 — skips when count == 0 (test: `test_flush_skips_post_when_count_zero`)
- [x] AC-B5 — exceptions logged (test: `test_flush_catches_exception_and_logs`)
- [x] AC-B6 — never raises (test: `test_flush_never_raises`)

### Part C — Feature flag + wiring
- [x] AC-C1 — env default false + parsed (tests: `test_feature_storage_ops_metering_defaults_false`, `test_feature_storage_ops_metering_parsed`)
- [x] AC-C2 — flag false → no meter (test: `test_meter_not_created_when_flag_false`)
- [x] AC-C3 — orchestrator + managed + flag → meter built (test: `test_meter_created_when_flag_true_orchestrator_mode`)
- [x] AC-C4 — standalone → meter None (test: `test_meter_none_in_standalone_mode`)
- [x] AC-C5 — workflow flushes at end (test: `test_execute_calls_flush_at_end`)
- [x] AC-C6 — analyze_and_caption flushes (test: `test_analyze_and_caption_calls_flush`)
- [x] AC-C7 — preview still flushes (test: `test_preview_mode_still_flushes_meter`)

## Test Results

```
1043 passed in 60.33s
```

## Quality Gates

- Format: ✅ `ruff format --check` clean (177 files)
- Lint: ✅ `ruff check` zero violations
- Type check: ✅ no new mypy errors on changed files (pre-existing unrelated errors only)
- Tests: ✅ 1043 passed, 0 failed
- Coverage on affected modules:
  - `services/managed_storage.py`: **88%** (≥80% ✅)
  - `services/storage_ops_meter.py`: **100%** (≥80% ✅)
  - `config/loader.py`: **96%**
  - `config/schema.py`: **98%**
  - `core/workflow.py`: **92%**
  - `web/service.py`: 72% (pre-existing baseline; new PUB-045 lines are covered by the wiring tests)
  - Overall on changed modules: **88%** (≥85% ✅)

## Notes

- **Counter placement**: increments happen *before* the boto3 call inside the `_list()`/`_download()`/etc. inner functions. This is what satisfies AC-A6 (404 still counted), AC-A8 (each retry counted), and AC-A3 across paginated and multi-call methods. The handoff "after the boto3 call succeeds" phrasing was relaxed to a unified "count per request attempt" — this is the only correct placement given that R2 bills failed requests too.
- **Tenacity retry caveat (AC-A8)**: the existing `download_image` wraps inner `ClientError` into `StorageError`, so `_is_transient_s3_error(StorageError)` always returns False and tenacity never retries on `ClientError`. The AC-A8 test instead raises `BotoConnectionError` (which propagates past the outer `except ClientError` and is recognized as transient), and monkeypatches `asyncio.sleep` to make retries instant. The counter placement guarantees that any future retry path (including boto3's adaptive retries on real R2) is counted correctly.
- **Defensive `getattr`**: `analyze_and_caption` and `WorkflowOrchestrator.execute` look up `_storage_ops_meter` via `getattr(self, "_storage_ops_meter", None)` so legacy tests that build instances via `__new__` (bypassing `__init__`) continue to work.
- **Preview mode**: `WorkflowOrchestrator.execute()` flushes the meter inside the `finally` block — so preview mode (`--preview` / `preview_mode=True`) also emits usage. This matches AC-C7 because R2 operations during preview are real billable requests.
- **Multiple flushes per day**: the idempotency key uses an hourly window (`r2ops:{tenant}:{yyyy-mm-dd}:{HH}`) per the handoff note. Within the same hour, the orchestrator dedupes subsequent flushes — first flush of the hour captures the counter; later flushes within that hour are server-side no-ops. Cross-hour flushes record independently.
