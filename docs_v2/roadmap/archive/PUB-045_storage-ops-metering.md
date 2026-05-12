# PUB-045: R2 Storage Ops Metering — Emit `storage_ops_requests` to Orchestrator

| Field | Value |
|-------|-------|
| **ID** | PUB-045 |
| **Category** | Foundation |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Done |
| **Dependencies** | PUB-034 (shipped — AI token metering), PUB-024 (shipped — ManagedStorage), Orchestrator BIL_10 (shipped — receiving side) |
| **GitHub Issue** | [#71](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/71) |

## Problem

The orchestrator has shipped BIL_10 — the metering contract declares `storage_ops_requests` (source `publisher_storage_ops`), the `POST /v1/billing/usage` endpoint accepts the metric, and the price book is seeded in production (0-price soak row, paid row effective 2026-06-01).

**Production currently shows zero `storage_ops_requests` events.** The publisher is the only entity that can emit them.

The publisher already has the generic infrastructure from PUB-034:
- `OrchestratorClient.post_usage()` can POST any metric to `/v1/billing/usage`
- `UsageMeter` provides fire-and-forget emission with exception swallowing

But **nothing counts R2 operations** and **nothing calls `post_usage()` with `metric=storage_ops_requests`**. `ManagedStorage` wraps ~12 boto3 methods (list, get, head, put, delete, copy) without any operation counting. R2 Class A and Class B request costs are not being recovered.

## Desired Outcome

After any `ManagedStorage` method executes an S3/R2 API call, the operation is counted. At the end of each workflow run (CLI or web), accumulated counts are flushed to the orchestrator as a single `storage_ops_requests` usage event per UTC day. Standalone (non-orchestrator) mode is unaffected. The feature is gated behind a flag that defaults to **off**.

---

## Part A — Thread-safe operation counter in `ManagedStorage`

**File**: `publisher_v2/src/publisher_v2/services/managed_storage.py`

Add an atomic counter that increments on every S3 API call. The counter must be thread-safe because `ManagedStorage` methods wrap boto3 calls in `asyncio.to_thread`.

```python
import threading

class ManagedStorage:
    def __init__(self, config: ManagedStorageConfig) -> None:
        # ... existing init ...
        self._ops_count = 0
        self._ops_lock = threading.Lock()

    def _count_ops(self, n: int = 1) -> None:
        """Increment the R2 operation counter (thread-safe)."""
        with self._ops_lock:
            self._ops_count += n

    def drain_ops_count(self) -> int:
        """Atomically read and reset the operation counter. Returns the count since last drain."""
        with self._ops_lock:
            count = self._ops_count
            self._ops_count = 0
            return count
```

Each S3-calling method must call `self._count_ops()` after the boto3 call succeeds. Methods that make multiple S3 calls (e.g. `archive_image` does copy + delete + sidecar copy + sidecar delete) count each individual API call.

### Operation count per method

| Method | S3 calls | Count |
|--------|----------|-------|
| `list_images` | `list_objects_v2` (paginated) | 1 per page |
| `list_images_with_hashes` | `list_objects_v2` (paginated) | 1 per page |
| `download_image` | `get_object` | 1 |
| `get_temporary_link` | `generate_presigned_url` | 0 (local signing, no API call) |
| `get_file_metadata` | `head_object` | 1 |
| `write_sidecar_text` | `put_object` | 1 |
| `download_sidecar_if_exists` | `get_object` | 1 (even if 404 — R2 bills the request) |
| `archive_image` | copy + delete (image) + copy + delete (sidecar, may fail) | 2–4 |
| `move_image_with_sidecars` | copy + delete (image) + copy + delete (sidecar, may fail) | 2–4 |
| `delete_file_with_sidecar` | delete (image) + delete (sidecar, suppressed) | 1–2 |
| `get_thumbnail` | delegates to `download_image` (counted there) | 0 (avoid double-count) |

### Acceptance Criteria

- **AC-A1**: `ManagedStorage` has `_ops_count` (int) and `_ops_lock` (threading.Lock) instance attributes initialized in `__init__`.
- **AC-A2**: `drain_ops_count()` atomically reads and resets the counter, returning the accumulated count.
- **AC-A3**: Every S3-calling method listed in the "Operation count per method" table increments the counter by the documented count (including per-page increments for paginated list calls).
- **AC-A4**: `get_temporary_link` does NOT increment the counter (presigned URL generation is a local operation).
- **AC-A5**: `get_thumbnail` does NOT double-count (it delegates to `download_image` which counts).
- **AC-A6**: Failed S3 calls (e.g. `download_sidecar_if_exists` returning 404) still increment the counter — R2 bills the request regardless.
- **AC-A7**: Counter is thread-safe — concurrent `asyncio.to_thread` calls do not lose increments.
- **AC-A8**: Retried S3 calls (via `@retry` decorator) count each attempt — if a method retries twice before succeeding, the counter reflects all 3 API calls.

---

## Part B — `StorageOpsMeter` service

**File**: `publisher_v2/src/publisher_v2/services/storage_ops_meter.py`

A dedicated meter that reads from the `ManagedStorage` counter and emits to the orchestrator. Separated from `UsageMeter` because the emission pattern differs (aggregated counter drain vs per-event emission).

```python
class StorageOpsMeter:
    def __init__(
        self,
        client: OrchestratorClient,
        tenant_id: str,
        storage: ManagedStorage,
    ) -> None:
        self._client = client
        self._tenant_id = tenant_id
        self._storage = storage
        self._logger = logging.getLogger("publisher_v2.storage_ops_metering")

    async def flush(self) -> None:
        """Drain the storage ops counter and emit to orchestrator. Never raises."""
        count = self._storage.drain_ops_count()
        if count <= 0:
            return
        try:
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            await self._client.post_usage(
                tenant_id=self._tenant_id,
                metric="storage_ops_requests",
                quantity=count,
                unit="requests",
                idempotency_key=f"r2ops:{self._tenant_id}:{today}",
                occurred_at=datetime.now(UTC).isoformat(),
                source="publisher_storage_ops",
            )
        except Exception:
            log_json(
                self._logger,
                logging.WARNING,
                "storage_ops_metering_failed",
                metric="storage_ops_requests",
                quantity=count,
                tenant_id=self._tenant_id,
            )
```

**Idempotency note**: The daily key `r2ops:{tenant_id}:{yyyy-mm-dd}` means that if `flush()` is called multiple times on the same day, the **first** call records the event and subsequent calls are treated as duplicates by the orchestrator (no second debit). This is acceptable for v1 — the first flush of the day captures the count up to that point, and any later flushes within the same day will be no-ops server-side. A future enhancement could use hourly keys.

**Important**: Because the orchestrator deduplicates on the idempotency key, only the **first** `flush()` per UTC day actually records a quantity. If the publisher runs multiple workflows per day, the counter should be flushed at the end of each run and the idempotency key must account for this. For v1, the simplest correct approach is to include a monotonic sequence or use hourly windows. **Recommendation**: use `r2ops:{tenant_id}:{yyyy-mm-dd}:{HH}` (hourly window) to allow multiple flushes per day while still being deterministic and replay-safe.

### Acceptance Criteria

- **AC-B1**: `StorageOpsMeter` exists in `publisher_v2/services/storage_ops_meter.py` with a `flush()` method.
- **AC-B2**: `flush()` calls `storage.drain_ops_count()` and, if count > 0, POSTs to `/v1/billing/usage` with `metric="storage_ops_requests"`, `unit="requests"`, `source="publisher_storage_ops"`, `quantity=<count>`.
- **AC-B3**: Idempotency key follows the shape `r2ops:{tenant_id}:{yyyy-mm-dd}:{HH}` (hourly window).
- **AC-B4**: If `drain_ops_count()` returns 0, no POST is made (skip no-op emission).
- **AC-B5**: If `post_usage()` raises any exception, `flush()` catches it, logs via `log_json` with `event="storage_ops_metering_failed"`, and returns normally. The caller's workflow continues.
- **AC-B6**: `flush()` never raises.

---

## Part C — Feature flag and wiring

### Feature flag

**Env var**: `FEATURE_STORAGE_OPS_METERING`
**Default**: `false` (off by default per BIL_10 safe rollout plan)

Add to `FeaturesConfig` in the schema and to the loader, following the pattern of existing feature flags (`FEATURE_ANALYZE_CAPTION`, `FEATURE_PUBLISH`, etc.).

In orchestrator mode (v2 schema), the flag can also be driven by runtime config (similar to other feature flags).

### Integration points

1. **`WebImageService.__init__`** (orchestrated path): When `runtime is not None` and `config_source.orchestrator_client is not None` and storage is `ManagedStorage` and `FEATURE_STORAGE_OPS_METERING` is enabled, construct a `StorageOpsMeter`. Store as `self._storage_ops_meter: StorageOpsMeter | None`.

2. **`WebImageService.analyze_and_caption()`**: After the method completes (success or failure), call `await self._storage_ops_meter.flush()` if meter is not `None`.

3. **`WorkflowOrchestrator.__init__`**: Add optional `storage_ops_meter: StorageOpsMeter | None = None` constructor parameter.

4. **`WorkflowOrchestrator.execute()`**: At the end of the method (after all storage operations), call `await self._storage_ops_meter.flush()` if meter is not `None`.

5. **`WebImageService._ensure_orchestrator()`**: Pass `self._storage_ops_meter` when constructing `WorkflowOrchestrator`.

6. **Web curation endpoints** (`curate`, `delete`, library browsing): These also use `ManagedStorage` and generate R2 requests. The counter increments automatically; the next `flush()` captures them.

7. **Standalone mode**: `storage_ops_meter` is `None`. Counter still increments in `ManagedStorage` (harmless) but is never drained/emitted.

### Acceptance Criteria

- **AC-C1**: `FEATURE_STORAGE_OPS_METERING` env var exists, defaults to `false`, parsed via `parse_bool_env`.
- **AC-C2**: When the flag is `false`, no `StorageOpsMeter` is constructed and no storage ops metering occurs.
- **AC-C3**: When the flag is `true` in orchestrator mode with `ManagedStorage`, a `StorageOpsMeter` is constructed and `flush()` is called after workflow execution.
- **AC-C4**: In standalone mode, `storage_ops_meter` is `None` regardless of the flag value.
- **AC-C5**: `WorkflowOrchestrator.execute()` calls `flush()` at the end (after all storage operations complete).
- **AC-C6**: `WebImageService.analyze_and_caption()` calls `flush()` after completion.
- **AC-C7**: In preview mode (`--preview` flag), the counter still increments and `flush()` still emits — preview mode does not suppress metering because R2 operations still incur real costs.

---

## Non-Goals

- Class A vs Class B split (single blended counter in v1)
- Exact reconciliation with Cloudflare invoices (approximation metric)
- Scheduled/cron-based emission (v1 uses end-of-workflow flush)
- Local billing ledger for standalone mode
- UI display of storage ops counts
- Counting operations on `DropboxStorage` (only `ManagedStorage` / R2)

## Quality Gates

- `ruff check` — zero violations in changed files
- `mypy` — zero errors
- `pytest` — all existing tests pass; new tests for `drain_ops_count`, `StorageOpsMeter`, feature flag wiring
- Coverage ≥ 80% on affected modules

## Implementation Notes

- Thread-safe counter: use `threading.Lock` (not `asyncio.Lock`) because the counter is incremented inside `asyncio.to_thread` wrappers.
- Test `drain_ops_count()` with concurrent increments to verify thread safety.
- Test `StorageOpsMeter.flush()` by mocking `OrchestratorClient.post_usage` — verify correct args and exception swallowing.
- For paginated list calls, count pages by incrementing inside the paginator loop (not a fixed count).
- The `@retry` decorator on `ManagedStorage` methods means a retried S3 call generates additional API calls. Each retry is a real R2 request and should be counted. The simplest correct approach: count inside the inner `_list()`, `_download()`, etc. functions that `asyncio.to_thread` wraps.

## Deployment Checklist

1. **Orchestrator prerequisite** (already done): `price_book_entries` row for `storage_ops_requests` exists in production (0-price soak row seeded, paid row effective 2026-06-01).
2. **Deploy publisher** with `FEATURE_STORAGE_OPS_METERING=false` (default).
3. **Enable in staging**: set `FEATURE_STORAGE_OPS_METERING=true`, observe usage events for one full day.
4. **Enable in production**: set `FEATURE_STORAGE_OPS_METERING=true`.
5. **Verify**: run orchestrator query `SELECT COUNT(*) FROM usage_events WHERE metric='storage_ops_requests' AND occurred_at > now() - interval '24 hours'` — should show non-zero rows.
6. **Close** orchestrator issue #218.

## Related

- [PUB-034: Usage Metering](archive/PUB-034_usage-metering.md) — AI token metering (shipped, provides `OrchestratorClient.post_usage()` and `UsageMeter`)
- [PUB-024: Managed Storage Adapter](archive/PUB-024_managed-storage-adapter.md) — `ManagedStorage` class (shipped)
- Orchestrator BIL_10 spec: `docs/10_Roadmap/archive/BIL_10_R2RequestCostRecoveryPublisherMetric.md`
- Orchestrator metering contract: `docs/02_Architecture/metering_contract.md`
- Orchestrator issue [#218](https://github.com/dhirmadi/platform-orchestrator/issues/218) — "Verify publisher emits `storage_ops_requests` in production"
- Orchestrator issue [#217](https://github.com/dhirmadi/platform-orchestrator/issues/217) — "Align R2 storage billing with Cloudflare cost model"
- Publisher issue [#57](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/57) — original metering integration (closed, covered AI tokens only)

---

## Change History

| Date | Change |
|------|--------|
| 2026-05-12 | Spec hardened for Claude Code handoff — added AC-A8 (retry counting), AC-C7 (preview mode behavior), clarified AC-A3 table reference |
