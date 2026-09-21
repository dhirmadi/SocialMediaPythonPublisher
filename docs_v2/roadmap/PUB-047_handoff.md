# Implementation Handoff: PUB-047 — Reliability Batch (R2 Retries, Listing Cost, Meter Flush, Postgres Bounds)

**Hardened:** 2026-09-21
**Status:** Ready for implementation

This item is four independent sub-fixes (#183–#186), each with its own PR. Implement and land
them in this order — later ones don't depend on earlier ones, but this order matches risk (retry
correctness first, cost second, latency third, fail-closed safety last).

## For Claude Code

### Test-first targets

| AC | Sub-issue | Test file | Test name (exact function) |
|----|-----------|-----------|-----------------------------|
| AC1 | #183 | `publisher_v2/tests/test_managed_storage.py` | `test_list_images_retries_on_slowdown_then_succeeds` |
| AC1 | #183 | `publisher_v2/tests/test_managed_storage.py` | `test_download_image_retries_on_slowdown_then_succeeds` |
| AC2 | #183 | `publisher_v2/tests/test_managed_storage.py` | `test_slowdown_on_every_attempt_raises_storage_error_with_client_error_cause` |
| AC2 | #183 | `publisher_v2/tests/test_managed_storage.py` | `test_404_is_not_retried` |
| AC3 | #183 | `publisher_v2/tests/test_managed_storage.py` | `test_endpoint_connection_error_raises_storage_error_not_botocore_exception` |
| — (scope note, not a numbered AC) | #183 | `publisher_v2/tests/test_managed_storage.py` | `test_delete_object_wraps_endpoint_connection_error_in_storage_error` — the ten `@retry`-decorated methods are AC1–AC3's contract; this one extra test on a non-retried `#96` object-level method (`delete_object`) only if its except-clause is touched during the refactor, so the widening isn't coverage-gate-only on that path |
| AC4 | #184 | `publisher_v2/tests/test_managed_storage.py` | `test_list_images_passes_delimiter_and_bills_one_page_per_1000_live_keys` |
| AC4 | #184 | `publisher_v2/tests/test_managed_storage.py` | `test_list_images_with_hashes_passes_delimiter` |
| AC5 | #185 | `publisher_v2/tests/web/test_web_analyze_storage_ops_meter.py` | `test_analyze_returns_under_one_second_when_orchestrator_never_responds` |
| AC6 | #185 | `publisher_v2/tests/test_workflow_lease_meter_order.py` | `test_lease_release_happens_before_meter_flush_in_finally` |
| AC6 | #185 | `publisher_v2/tests/test_workflow_lease_meter_order.py` | `test_cancellation_during_meter_flush_still_leaves_lease_released` |
| AC7 | #186 | `publisher_v2/tests/test_db_connect_args.py` | `test_init_db_passes_connect_and_command_timeout_from_runtime_settings` |
| AC7 | #186 | `publisher_v2/tests/test_runtime_settings.py` | `test_db_timeout_fields_read_from_env_with_defaults` |
| AC8 | #186 | `publisher_v2/tests/test_workflow_publish_store_unavailable.py` | `test_acquire_lease_raising_aborts_run_with_publish_store_unavailable` |
| AC8 | #186 | `publisher_v2/tests/test_workflow_publish_store_unavailable.py` | `test_acquire_lease_hanging_past_claim_budget_aborts_run` |
| AC9 | #186 | `publisher_v2/tests/test_workflow_publish_store_unavailable.py` | `test_no_publish_store_configured_behaves_as_before` |

The **Test name** column is the exact `pytest` function name to create — the only spec-to-test
traceability link `/verify` and `/product-review-delivery` check against. If a name must change,
record the new mapping in the summary doc; don't silently rename.

### Mock boundaries

| External service / seam | Mock strategy | Existing fixture / pattern to reuse |
|---|---|---|
| boto3 S3 client (`ManagedStorage`) | `unittest.mock.patch("publisher_v2.services.managed_storage.boto3")` + `MagicMock()` client, fake paginator | `tests/test_managed_storage.py::mock_s3_client`, `storage` fixtures |
| Tenacity backoff delay | Extract the shared retry decorator + wait callable to module level (mirror `_dropbox_retry`/`_dropbox_wait` in `services/storage.py`); monkeypatch the wait callable to `0.0` | `tests/test_storage_error_paths.py::_fast_retries` |
| `OrchestratorClient.post_usage` | `unittest.mock.AsyncMock`; for AC5, an `AsyncMock` whose side effect awaits an `asyncio.Event` that the test never sets, so the coroutine never resolves | `tests/test_storage_ops_meter.py::_build_meter` |
| `StorageOpsMeter` inside `WebImageService` | Construct `WebImageService` the way `tests/web/test_web_analyze_sidecar_cache.py::_make_service` does, then set `service._storage_ops_meter = StorageOpsMeter(client=<hanging AsyncMock client>, tenant_id=..., storage=service.storage)`. That fixture's `service.storage` is a `DropboxStorage` (patched via `dropbox.Dropbox`), which has **no `_count_ops`/`drain_ops_count`** — those are `ManagedStorage`-only (PUB-045's R2 counter). Do **not** call `service.storage._count_ops(...)`; instead `service.storage.drain_ops_count = MagicMock(return_value=5)` directly on the storage instance so the meter sees a non-zero batch to hold | new — build on `_make_service` |
| `WorkflowOrchestrator._storage_ops_meter` / `_publish_store` for AC6 | Two `unittest.mock.AsyncMock`s (or a tiny fake class) that each append a string to a shared `list[str]` call-order log before doing their real work, so the test asserts on list order, not timing | new — see AC6 wording in the roadmap item for the exact recorded-order assertion |
| `store.acquire_lease` / `store.posted_platforms` for AC8 | `unittest.mock.AsyncMock(side_effect=RuntimeError(...))` for the raising case; `AsyncMock(side_effect=lambda *a, **kw: asyncio.sleep(999))` for the hang case, driven under a real (small) `publish_claim_timeout_seconds` so `asyncio.wait_for` fires for real rather than being mocked away | `tests/test_publish_store.py` fixtures for a real `PublishStore` when a working baseline is also needed (AC9) |
| Postgres engine kwargs (AC7) | Do **not** connect to a real Postgres. Patch `publisher_v2.db.create_async_engine` (the name imported into `db/__init__.py`) with a `MagicMock`, call `init_db(settings=...)`, and assert on `create_async_engine.call_args.kwargs["connect_args"]` | new — same spirit as `tests/test_caption_history_db.py` but kwargs-only, no `aiosqlite` |

### Files likely touched

| Area | Files to modify | Files to create |
|---|---|---|
| #183 retries | `publisher_v2/src/publisher_v2/services/managed_storage.py` | — |
| #184 listing cost | `publisher_v2/src/publisher_v2/services/managed_storage.py` (`list_images`, `list_images_with_hashes` only — `list_objects` already has `Delimiter="/"`) | — |
| #185 meter + lease order | `publisher_v2/src/publisher_v2/services/storage_ops_meter.py`, `publisher_v2/src/publisher_v2/core/workflow.py` (finally-block reorder only), `publisher_v2/src/publisher_v2/web/service.py` (no logic change expected — `flush()` becoming non-blocking is transparent to this call site) | `publisher_v2/tests/web/test_web_analyze_storage_ops_meter.py`, `publisher_v2/tests/test_workflow_lease_meter_order.py` |
| #186 Postgres + claim budget | `publisher_v2/src/publisher_v2/db/__init__.py`, `publisher_v2/src/publisher_v2/config/runtime_settings.py`, `publisher_v2/src/publisher_v2/core/exceptions.py` (new `PublishStoreUnavailableError`), `publisher_v2/src/publisher_v2/core/workflow.py` (`_claim_publish_targets`, its call site in `execute()`) | `publisher_v2/tests/test_db_connect_args.py`, `publisher_v2/tests/test_workflow_publish_store_unavailable.py` |

### New config surface (all via `RuntimeSettings` / `load_runtime_settings()` — no INI, no orchestrator contract change)

| Field | Env var | Default | Used by |
|---|---|---|---|
| `db_connect_timeout_seconds: float` | `DB_CONNECT_TIMEOUT_SECONDS` | `10.0` | `db/__init__.py::init_db` → asyncpg `connect_args["timeout"]` |
| `db_command_timeout_seconds: float` | `DB_COMMAND_TIMEOUT_SECONDS` | `30.0` | `db/__init__.py::init_db` → asyncpg `connect_args["command_timeout"]` |
| `publish_claim_timeout_seconds: float` | `PUBLISH_CLAIM_TIMEOUT_SECONDS` | `10.0` | `core/workflow.py::_claim_publish_targets` → `asyncio.wait_for` around the claim |

Follow the existing `_float_env` lenient-parse-with-fallback pattern in `runtime_settings.py`; no
new clamping is specified, so don't invent one (contrast with `publish_timeout_seconds`, which has
a documented historical floor — these two don't need one).

### Non-negotiables for this item

- [ ] Preview mode: unaffected — none of the four fixes touch preview's early-return or field
      population; `_claim_publish_targets` is only reached when `will_publish` is true, which is
      already false for `preview_mode` (existing guard at the `execute()` call site).
- [ ] Secrets: none introduced; no new credential or token handling.
- [ ] Auth: N/A — no web endpoint contract changes.
- [ ] Async hygiene: `StorageOpsMeter`'s background drain task must not be awaited from the request
      path (that's the bug being fixed); the boto3 calls stay behind `asyncio.to_thread` (unchanged).
- [ ] Backward compatibility: `init_db()`'s new `settings` parameter is optional and defaults to
      `load_runtime_settings()`; both existing zero-arg call sites (`app.py:113`, `web/app.py:122`)
      and the test call site (`test_caption_history_db.py:377`) keep working unchanged.
      `StorageOpsMeter.flush()`, `start_periodic_flush()`, `stop_periodic_flush()` keep their names
      and signatures; only `flush()`'s and `stop_periodic_flush()`'s internals change, plus a new
      `aclose()` and `pending_batch_count()` method are added (additive, not breaking).
      CLI exit codes are unchanged (0/1 only) — AC8 fails closed but still resolves to exit 1 via
      the existing `0 if result.success else 1`, not a new exit code.
- [ ] Coverage: ≥80% on `managed_storage.py`, `storage_ops_meter.py`, `db/__init__.py`,
      `runtime_settings.py`, and the touched parts of `workflow.py`; ≥85% overall.

### Sequencing / dependency notes

- #183 and #184 both touch `managed_storage.py` but different methods (retry predicate/except
  clauses vs. the two listing paginators) — land #183 first so #184's tests inherit the fast-retry
  fixture if the shared decorator refactor happens in #183.
- #185 and #186 both touch `core/workflow.py`'s `execute()`/`_claim_publish_targets`, but in
  different, non-overlapping regions (the `finally` block's flush/lease order vs. the claim call
  and its exception handling) — no merge conflict expected if landed in either order.

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-047_reliability-batch.md
```
