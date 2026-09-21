# PUB-047 — Reliability Batch (R2 Retries, Listing Cost, Meter Flush, Postgres Bounds): Implementation Summary

**Status:** Implementation Complete
**Date:** 2026-09-21
**Sub-issues:** #183 (retries), #184 (listing cost), #185 (meter flush), #186 (Postgres + claim budget)

## Files Changed

### Source
- `publisher_v2/src/publisher_v2/services/managed_storage.py` — #183: `_is_transient_s3_error` unwraps `StorageError.__cause__`; `except ClientError` widened to `except (ClientError, EndpointConnectionError, BotoConnectionError)` on the ten `@retry`-decorated legacy methods plus `delete_object`; the ten duplicate `@retry(...)` instantiations collapsed into module-level `_managed_retry` with a late-bound `_managed_wait`. #184: `Delimiter="/"` on the `list_images` / `list_images_with_hashes` paginators.
- `publisher_v2/src/publisher_v2/services/storage_ops_meter.py` — #185: `flush()` is now fire-and-forget (sync counter drain + `_pending` append + background drain task); `_drain_pending` makes one bounded pass per run with `asyncio.wait_for(_DRAIN_ATTEMPT_TIMEOUT_SECONDS=5.0)`; new `aclose()` (bounded by `_ACLOSE_DEADLINE_SECONDS=10.0`, logs `storage_ops_meter_undrained_queue`, never raises) and `pending_batch_count()`; `stop_periodic_flush()` keeps its name and delegates to `aclose()`.
- `publisher_v2/src/publisher_v2/core/workflow.py` — #185: `execute()`'s `finally` now runs the shielded `pending_leases` release **before** `meter.flush()` (source-order swap only). #186: `_claim_publish_targets` wraps `posted_platforms` + `acquire_lease` in one `asyncio.wait_for(publish_claim_timeout_seconds)` and raises `PublishStoreUnavailableError` instead of the fail-open fallback; `execute()` catches it at the call site.
- `publisher_v2/src/publisher_v2/core/exceptions.py` — #186: new `PublishStoreUnavailableError(PublishingError)`.
- `publisher_v2/src/publisher_v2/db/__init__.py` — #186: `init_db(settings: RuntimeSettings | None = None)` passing `connect_args={"timeout", "command_timeout"}` to `create_async_engine`.
- `publisher_v2/src/publisher_v2/config/runtime_settings.py` — #186: three new `_float_env` fields (no clamping).

### Tests
- `publisher_v2/tests/test_managed_storage.py` — +193 lines: `TestManagedStorageRetryLayer`, `TestListingDelimiter`, `fast_managed_retries` fixture.
- `publisher_v2/tests/test_storage_ops_meter.py` — +312 lines: `aclose()`, drain-attempt timeout, `_cancel_task`, periodic flush, pending-queue bounds, drain-failure logging.
- `publisher_v2/tests/test_runtime_settings.py` — +32 lines: `TestDbAndClaimTimeouts`; three new env vars added to `_ENV_KEYS`.
- `publisher_v2/tests/test_db_connect_args.py` (new) — AC7 plus `dispose_engine` / `check_connectivity` coverage.
- `publisher_v2/tests/test_workflow_lease_meter_order.py` (new) — AC6.
- `publisher_v2/tests/test_workflow_publish_store_unavailable.py` (new) — AC8, AC9.
- `publisher_v2/tests/web/test_web_analyze_storage_ops_meter.py` (new) — AC5.
- `publisher_v2/tests/web/test_web_publish_store_unavailable_response.py` (new) — supplementary AC8 web-call-site guard (see below).

### Docs
- `docs_v2/05_Configuration/CONFIGURATION.md` — documented `PUBLISH_CLAIM_TIMEOUT_SECONDS`, `DB_CONNECT_TIMEOUT_SECONDS`, `DB_COMMAND_TIMEOUT_SECONDS`, including the fail-closed behavior change.

## Acceptance Criteria

- [x] AC1 — transient `SlowDown` retried then succeeds (`test_list_images_retries_on_slowdown_then_succeeds`, `test_download_image_retries_on_slowdown_then_succeeds`)
- [x] AC2 — permanent `SlowDown` → `StorageError` with `ClientError` `__cause__`; 404 not retried (`test_slowdown_on_every_attempt_raises_storage_error_with_client_error_cause`, `test_404_is_not_retried`)
- [x] AC3 — `EndpointConnectionError` → `StorageError`, not raw botocore (`test_endpoint_connection_error_raises_storage_error_not_botocore_exception`; plus scope-note `test_delete_object_wraps_endpoint_connection_error_in_storage_error`)
- [x] AC4 — `Delimiter="/"` passed; one page per 1,000 live keys (`test_list_images_passes_delimiter_and_bills_one_page_per_1000_live_keys`, `test_list_images_with_hashes_passes_delimiter`)
- [x] AC5 — analyze returns under 1s against a never-responding orchestrator; batch still held (`test_analyze_returns_under_one_second_when_orchestrator_never_responds`)
- [x] AC6 — lease release recorded before `flush()` is invoked; `CancelledError` still propagates (`test_lease_release_happens_before_meter_flush_in_finally`, `test_cancellation_during_meter_flush_still_leaves_lease_released`)
- [x] AC7 — engine `connect_args` from the new settings fields (`test_init_db_passes_connect_and_command_timeout_from_runtime_settings`, `test_db_timeout_fields_read_from_env_with_defaults`)
- [x] AC8 — claim failure/timeout aborts fail-closed with `error="publish_store_unavailable"`, nothing published (`test_acquire_lease_raising_aborts_run_with_publish_store_unavailable`, `test_acquire_lease_hanging_past_claim_budget_aborts_run`)
- [x] AC9 — no publish store configured → file-state path unchanged (`test_no_publish_store_configured_behaves_as_before`)

All 16 exact test-function names from the handoff's Test-first targets table exist as written. **Zero name drift.**

**One supplementary test, not in the handoff table:** AC8's final clause (the `/publish` call site returns a normal `PublishResponse` with `any_success=False`, not a 500) had no named test. Added as `publisher_v2/tests/web/test_web_publish_store_unavailable_response.py::test_publish_image_returns_empty_publish_response_when_publish_store_unavailable`. It asserts at the service boundary, which is where the AC's causal claim lives (`web/app.py` only maps raised exceptions to non-200s).

## Test Results

```
Using --randomly-seed=442983949
1735 passed, 1 skipped, 83 warnings in 81.47s
```

## Quality Gates

- Format: ✅ `241 files already formatted`
- Lint: ✅ `All checks passed!`
- Type check: ✅ `Success: no issues found in 64 source files`
- Tests: ✅ 1735 passed, 0 failed, 1 skipped
- Coverage: ✅ **TOTAL 93%** (gate 85). Affected modules: `storage_ops_meter.py` 100%, `db/__init__.py` 100%, `core/exceptions.py` 100%, `runtime_settings.py` 99%, `core/workflow.py` 94%, `managed_storage.py` 91% — all ≥80%.

## Subagent Verdicts

- `code-reviewer`: **PASS WITH NITS** — all five judgement calls independently verified (including mutation-testing the retry-decorator collapse against git history and confirming `test_404_is_not_retried` is a real guard). Its one must-fix (W1) and two nits (N1, N5) were routed back to `developer` and resolved; re-verified green.
- `security-auditor`: **PASS** — no path publishes with a store configured but no acquired lease; preview never reaches the claim; the shielded lease release strictly precedes the meter; `EndpointConnectionError` endpoint URLs are caught by the existing `R2_ENDPOINT_REDACTED` sanitizer; `web/` diff is empty.

## Notes — deviations and decisions

1. **`await asyncio.sleep(0)` at the end of `flush()`** (beyond the spec's literal "awaits nothing"). Keeps a healthy orchestrator posted within the same call — removing it fails 8 tests, 6 pre-existing. Reviewer mutation-verified it reintroduces no blocking: AC5's hung-orchestrator test passes identically with and without it. *Caveat:* this leans on CPython 3.12's `wait_for` awaiting a bare coroutine without `ensure_future`; if that changes, those 6 legacy tests break (test-only fragility).
2. **Drain loop makes one bounded pass per run** rather than the spec's literal "loops while `_pending` is non-empty". The literal reading hot-spins against a dead orchestrator. First implemented as stop-at-first-failure, which the reviewer caught (W1) as a head-of-line-blocking regression vs. HEAD; corrected to a snapshot pass that keeps a failed batch (original idempotency key) and continues to the next. Drains the whole queue on the healthy path; exactly one attempt per pending batch when the orchestrator is down. **The spec's #185 wording should be tightened to match.**
3. **`delete_object`'s `except` clause widened** although the six `#96` object-level methods are "out of scope". Sanctioned by the handoff's conditional scope note and covered by a test. Leaves those six inconsistent — `head_object`'s latent leak against its own "never raises" docstring is untouched and remains a follow-up.
4. **Inner narrow `except ClientError` handlers left narrow** (404-tolerant sidecar reads in `download_sidecar_if_exists` / `archive_image` / `move_image_with_sidecars`). Widening them would swallow connection errors into "no sidecar"/"skip" instead of surfacing them for retry.
5. **`except Exception` in `_claim_publish_targets`** rather than naming `TimeoutError`: on 3.12 `asyncio.TimeoutError is TimeoutError` and is an `Exception`, so one clause covers both; `CancelledError` (a `BaseException`) correctly still propagates rather than being laundered into `publish_store_unavailable`.

## Known trade-offs (not defects)

- **Orphaned-lease-on-timeout.** The single `wait_for` budget spans `posted_platforms` + `acquire_lease` (the shape the spec pinned). A timeout firing after the server granted the lease but before the response is read leaves the row leased with no local token, so the image is unpublishable until `PUBLISH_LEASE_TTL_SECONDS` expires. Strictly safer than the old fail-open behavior — an availability cost, not a correctness one. Relevant to PUB-054.
- **`_cancel_task` suppresses `Exception` alongside `CancelledError`** (`storage_ops_meter.py`), so a caller cancelled during `aclose()`'s `await task` has that cancellation consumed. Shutdown-only and bounded by the 10s deadline; flagged by both reviewers as a nit, deliberately not changed.
- **Retry budget is unpinned by tests.** `_managed_wait` is monkeypatched to `0.0`, so no test asserts `stop_after_attempt(3)` / `wait_exponential(1,1,8)`; AC1's "configured backoff" is satisfied by attempt count only. An edit to `_EXPONENTIAL_WAIT` would pass the suite silently.
- **Pre-existing, unchanged by this item:** `SanitizingFilter` covers `record.msg`/`record.args` but not `record.exc_text`; an `InvalidAccessKeyId` `ClientError` can echo the access key ID (not the secret) past the sanitizer's `access_key_id`-prefixed pattern.

## PR #214 review response

The review (2026-09-21) confirmed all nine ACs MET against the code and ran the gates locally. Seven items were raised; all are resolved or tracked.

| # | Item | Resolution |
|---|---|---|
| 1 | **Blocking:** TruffleHog red — a credentialed `postgres://` URL (userinfo redacted here on purpose) in `test_db_connect_args.py` | Replaced with `postgresql+asyncpg://localhost/appdb`. **No scanner exclusion added** (PUB-055 is about to make these checks blocking). |
| 2 | **Blocking:** commit `5c641ff` ("code reviewer memory") widened harness push permissions and rode into the PR | Branch rebased onto `origin/main`, dropping `5c641ff` entirely. `.claude/settings.json` and the 22 agent-memory files are no longer in the PR. The commit remains unpushed on local `main` and needs its own PR — see below. |
| 3 | `init_db(settings=None)` added an eighth `load_runtime_settings()` constructor fallback | Parameter is now **required**; both call sites (`app.py`, `web/app.py`) pass the snapshot they already hold. |
| 4 | The three new timeouts accepted `0` and negatives; `PUBLISH_CLAIM_TIMEOUT_SECONDS=0` would abort every run with a phantom store outage | `field_validator` rejects `<= 0` with `ConfigurationError`. **Reject, not clamp** — `0.001` still works, which AC8's hang test depends on. |
| 5 | Spec marked `Done` while the index said `Proposal`; `Done` belongs to `/product-archive` after approval | Both set to `In Progress`. Archive after merge with the Verified evidence line. |
| 6 | The 5s per-attempt drain deadline is smaller than one `OrchestratorClient` call (3 × 5s), so a slow-but-alive orchestrator never delivers and under-bills | Filed as **#215**. Not blocking — idempotency keys make this a billing-completeness issue, not a correctness one. |
| 7 | Info: a cancellation during the shielded release now skips the flush | One-line comment added at the `meter.flush()` block so the order is not "fixed" back. |

Post-review suite: **1752 passed**, 1 skipped; coverage 92.48%.

**Pre-existing, not fixed here:** `test_caption_history_db.py` lines 368, 390-392 carry credential-shaped `postgres://` URLs with inline userinfo (not quoted here, so this file does not itself trip the scanner) dating to `23edf94c` (2026-05-13). They do not trip the current detector (single-letter userinfo fails its entropy/shape checks), but they should be normalised under PUB-055 before secret scans go blocking.

## Not done

- No commit was made — the change is left uncommitted in the working tree for review.
- The four sub-issues were implemented as one working tree, not the four separate PRs (#183–#186) the spec's Implementation Notes call for. Splitting for delivery is a git operation left to the operator.
