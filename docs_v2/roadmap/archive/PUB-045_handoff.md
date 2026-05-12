# Implementation Handoff: PUB-045 — R2 Storage Ops Metering

**Hardened:** 2026-05-12  
**Status:** Ready for implementation

---

## For Claude Code

### Test-first targets

| AC | Test file | Key test cases |
|----|-----------|----------------|
| AC-A1 | `publisher_v2/tests/services/test_managed_storage.py` | `test_init_creates_ops_counter_and_lock` |
| AC-A2 | `publisher_v2/tests/services/test_managed_storage.py` | `test_drain_ops_count_returns_and_resets`, `test_drain_ops_count_consecutive_calls` |
| AC-A3 | `publisher_v2/tests/services/test_managed_storage.py` | `test_list_images_increments_counter_per_page`, `test_download_image_increments_counter`, `test_write_sidecar_increments_counter`, `test_archive_image_increments_counter_2_to_4`, `test_move_image_increments_counter_2_to_4`, `test_delete_file_increments_counter_1_to_2` |
| AC-A4 | `publisher_v2/tests/services/test_managed_storage.py` | `test_get_temporary_link_does_not_increment_counter` |
| AC-A5 | `publisher_v2/tests/services/test_managed_storage.py` | `test_get_thumbnail_does_not_double_count` |
| AC-A6 | `publisher_v2/tests/services/test_managed_storage.py` | `test_download_sidecar_404_still_increments_counter` |
| AC-A7 | `publisher_v2/tests/services/test_managed_storage.py` | `test_counter_thread_safety_concurrent_increments` |
| AC-A8 | `publisher_v2/tests/services/test_managed_storage.py` | `test_retry_counts_each_attempt` |
| AC-B1 | `publisher_v2/tests/services/test_storage_ops_meter.py` | `test_storage_ops_meter_exists_with_flush_method` |
| AC-B2 | `publisher_v2/tests/services/test_storage_ops_meter.py` | `test_flush_calls_post_usage_with_correct_args` |
| AC-B3 | `publisher_v2/tests/services/test_storage_ops_meter.py` | `test_idempotency_key_format_hourly_window` |
| AC-B4 | `publisher_v2/tests/services/test_storage_ops_meter.py` | `test_flush_skips_post_when_count_zero` |
| AC-B5, B6 | `publisher_v2/tests/services/test_storage_ops_meter.py` | `test_flush_catches_exception_and_logs`, `test_flush_never_raises` |
| AC-C1 | `publisher_v2/tests/config/test_loader.py` | `test_feature_storage_ops_metering_defaults_false`, `test_feature_storage_ops_metering_parsed` |
| AC-C2 | `publisher_v2/tests/web/test_service.py` | `test_meter_not_created_when_flag_false` |
| AC-C3 | `publisher_v2/tests/web/test_service.py` | `test_meter_created_when_flag_true_orchestrator_mode` |
| AC-C4 | `publisher_v2/tests/web/test_service.py` | `test_meter_none_in_standalone_mode` |
| AC-C5 | `publisher_v2/tests/core/test_workflow.py` | `test_execute_calls_flush_at_end` |
| AC-C6 | `publisher_v2/tests/web/test_service.py` | `test_analyze_and_caption_calls_flush` |
| AC-C7 | `publisher_v2/tests/core/test_workflow.py` | `test_preview_mode_still_flushes_meter` |

### Mock boundaries

| External service | Mock strategy | Existing fixture |
|-----------------|---------------|------------------|
| boto3 S3 client | `unittest.mock.patch` on `self.client` methods | Create new fixture `mock_s3_client` |
| OrchestratorClient.post_usage | `unittest.mock.AsyncMock` | `tests/conftest.py::mock_orchestrator_client` |
| ManagedStorage.drain_ops_count | `unittest.mock.MagicMock` (for meter tests) | N/A — mock directly |

### Files likely touched

| Area | Files to modify | Files to create |
|------|-----------------|-----------------|
| Storage | `publisher_v2/src/publisher_v2/services/managed_storage.py` | — |
| Meter | — | `publisher_v2/src/publisher_v2/services/storage_ops_meter.py` |
| Config schema | `publisher_v2/src/publisher_v2/config/schema.py` | — |
| Config loader | `publisher_v2/src/publisher_v2/config/loader.py` | — |
| Web service | `publisher_v2/src/publisher_v2/web/service.py` | — |
| Workflow | `publisher_v2/src/publisher_v2/core/workflow.py` | — |
| Tests | `publisher_v2/tests/services/test_managed_storage.py` | `publisher_v2/tests/services/test_storage_ops_meter.py` |

### Non-negotiables for this item

- [ ] **Preview mode**: Counter increments and `flush()` emits even in preview mode (real R2 costs)
- [ ] **Secrets**: N/A — only tenant_id and counts involved
- [ ] **Auth**: N/A — internal metering, not user-facing
- [ ] **Never raises**: `flush()` must catch all exceptions and log, never propagate
- [ ] **Thread safety**: Use `threading.Lock` (not `asyncio.Lock`) because increments happen inside `asyncio.to_thread`
- [ ] **Coverage**: ≥80% on `managed_storage.py`, `storage_ops_meter.py`

### Implementation order

1. **Part A first** — Add counter to `ManagedStorage` with tests
2. **Part B second** — Create `StorageOpsMeter` with tests
3. **Part C last** — Wire up feature flag and integration points

### Key implementation details

**Counter placement**: Increment inside the inner `_list()`, `_download()`, etc. functions that `asyncio.to_thread` wraps, AFTER the boto3 call succeeds (or fails with 404 for sidecars).

**Paginated lists**: Increment inside the paginator loop, once per page:
```python
for page in paginator.paginate(...):
    self._count_ops()  # Count each page
    for obj in page.get("Contents", []):
        ...
```

**Idempotency key format**: `r2ops:{tenant_id}:{yyyy-mm-dd}:{HH}` (hourly window)

**Feature flag pattern**: Follow existing pattern in `loader.py`:
```python
storage_ops_metering_enabled=parse_bool_env(
    os.environ.get("FEATURE_STORAGE_OPS_METERING"), False, var_name="FEATURE_STORAGE_OPS_METERING"
)
```

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-045_storage-ops-metering.md
```

---

## Verification checklist (post-implementation)

- [ ] `ruff check` — zero violations in changed files
- [ ] `mypy` — zero errors
- [ ] `pytest` — all tests pass
- [ ] Coverage ≥ 80% on affected modules
- [ ] Manual test: set `FEATURE_STORAGE_OPS_METERING=true`, run workflow, verify usage event in orchestrator logs
