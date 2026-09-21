# PUB-047: Reliability Batch — R2 Retries, Listing Cost, Meter Flush, Postgres Bounds

| Field | Value |
|-------|-------|
| **ID** | PUB-047 |
| **Category** | Foundation |
| **Priority** | P0 |
| **Effort** | S |
| **Status** | Done |
| **Dependencies** | — |

## User Story

As a publisher operator, I want a single R2 throttle, an orchestrator outage or a Postgres blip to be absorbed rather than to fail a run, stall a response or publish without a lease, so that the daily publish is reliable and its storage bill stays flat.

## Problem

The 2026-09-21 review (tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177)) found four reliability holes, each verified by probe or by reading the cited lines:

1. **The managed-storage retry layer never fires.** Every `ManagedStorage` method wraps the boto call in `except ClientError: raise StorageError(...) from exc` *inside* the coroutine that `@retry` decorates, and `_is_transient_s3_error` (`services/managed_storage.py:53-64`) does not unwrap `StorageError.__cause__`. boto's own retries are disabled (`:98`). R2 therefore gets zero retries on `SlowDown`, `ServiceUnavailable` or any 5xx. The Dropbox predicate had the same bug and was fixed in #132; this one was not.
2. **Listings scan the whole root.** `list_images` and `list_images_with_hashes` (`:199`, `:235`) paginate with no `Delimiter`, so every LIST page under the root, including `archive/`, is billed and parsed on every cron run, every 30 s web refresh and every `ensure_known_image` call. Cost grows two keys per publish forever.
3. **The storage-ops meter flushes on the request path.** `core/workflow.py:919` and `web/service.py:700` `await meter.flush()` in `finally`, unshielded, before the shielded lease release; a flush retries up to 12 pending batches at up to 16 s each. An orchestrator outage turns into multi-minute response stalls and a cancellation during the flush skips the lease release.
4. **Postgres is unbounded and a store error fails open.** `db/__init__.py:55-61` sets no connect or statement timeout; the lease claim runs outside every deadline; any exception during the claim (`core/workflow.py:958-966`) publishes on every platform with no lease and unfenced marks.

## Desired Outcome

A throttled R2 call is retried and succeeds when the backend recovers. A listing of a root with N live images bills `ceil(N / 1000)` pages regardless of archive size. No request or workflow path awaits an orchestrator round-trip for metering, and the lease is released before any metering. Every Postgres call has a timeout, the lease claim is bounded, and with a store configured a store failure never results in a publish.

## Scope

**In scope:**
- `_is_transient_s3_error` unwraps `StorageError.__cause__`; raw botocore connection errors surface as `StorageError`
- `Delimiter="/"` on both listing paginators; client-side immediate-child filter kept as a belt
- `StorageOpsMeter.flush()` enqueues and returns; a background task drains one batch per attempt with a short deadline; `aclose()` drains with a bounded deadline; lease release moved ahead of any meter call
- `create_async_engine` with `connect_args={"timeout", "command_timeout"}` as `RuntimeSettings` fields; `_claim_publish_targets` wrapped in `asyncio.wait_for`; a distinct `publish_store_unavailable` outcome when a store is configured and the claim fails

**Out of scope:**
- Retry counts, backoff values or the idempotency key scheme from #92
- Selection through the store and the `publishing` lease state (PUB-054)
- Any change to the orchestrator contract

## Acceptance Criteria

- AC1: Given a fake client that raises `ClientError(SlowDown)` twice then succeeds, when `download_image` or `list_images` is called, then the call succeeds and the client was invoked three times with the configured backoff
- AC2: Given a client that raises `SlowDown` on every attempt, when any storage method is called, then a `StorageError` is raised whose `__cause__` is the last `ClientError`, and a 404 is not retried
- AC3: Given a client that raises `EndpointConnectionError` on every attempt, when any storage method is called, then a `StorageError` is raised, not a botocore exception (the current `except ClientError` clauses do not catch `EndpointConnectionError`/`ConnectionError`, so today it leaks raw — broaden the except clauses, not just the predicate)
- AC4: Given a fake paginator recording its kwargs, when `list_images` or `list_images_with_hashes` runs, then `Delimiter="/"` is passed and a root with N live keys and any number of archived keys counts one page per 1,000 live keys
- AC5: Given an `OrchestratorClient.post_usage` whose coroutine never returns (e.g. it awaits an `asyncio.Event` that is never set), when `WebImageService.analyze_and_caption` runs with a `StorageOpsMeter` built on that client and a non-zero drained op count, then the call (wrapped in `asyncio.wait_for(..., timeout=1.0)` in the test) completes without `TimeoutError`, and the meter still holds the undelivered batch afterward (exposed for the test via a `pending_batch_count() -> int` method on `StorageOpsMeter`, mirroring the read-only intent of `UsageMeter`'s queue but counting drained-and-not-yet-posted batches rather than raw queue depth)
- AC6: Given a `WorkflowOrchestrator` built with a fake `_storage_ops_meter` whose `flush()` is an `AsyncMock` that records a call order token and then hangs until cancelled, and a `_publish_store` fake whose `mark`/`_mark_publish` path also records a call order token, when a run that took a lease is cancelled while `execute()`'s `finally` block is running, then the lease-release token was recorded before the `flush()` token was even invoked (i.e. `finally` calls the lease-release block, under its existing `asyncio.shield`, strictly before it calls `meter.flush()` — the source-order swap in `core/workflow.py`'s `finally`, not a new synchronization primitive), and the `CancelledError` delivered during the hanging `flush()` propagates after the (already-shielded, already-completed) lease release, matching the existing re-raise behavior at the bottom of the `finally` block
- AC7: Given the engine is created, when its kwargs are inspected, then `connect_args` equals `{"timeout": settings.db_connect_timeout_seconds, "command_timeout": settings.db_command_timeout_seconds}`, where `RuntimeSettings.db_connect_timeout_seconds` (env `DB_CONNECT_TIMEOUT_SECONDS`, default `10.0`) and `RuntimeSettings.db_command_timeout_seconds` (env `DB_COMMAND_TIMEOUT_SECONDS`, default `30.0`) are new fields read the same way every other `RuntimeSettings` field is (`load_runtime_settings()`); `init_db()` gains an optional `settings: RuntimeSettings | None = None` parameter (defaulting to `load_runtime_settings()`) so its two existing zero-arg call sites (`app.py`, `web/app.py`) keep working unchanged
- AC8: Given a publish store whose `acquire_lease` (or the `posted_platforms` call immediately before it) raises, or hangs past a new `RuntimeSettings.publish_claim_timeout_seconds` field (env `PUBLISH_CLAIM_TIMEOUT_SECONDS`, default `10.0`) wrapping both in `asyncio.wait_for`, when the run reaches the claim, then `_claim_publish_targets` raises a new `PublishStoreUnavailableError` (added to `core/exceptions.py`, subclassing `PublishingError`) instead of returning a fail-open fallback list; `execute()` catches it at the call site, publishes nothing (no publisher is invoked, `publish_results == {}`), and returns `WorkflowResult(success=False, error="publish_store_unavailable", ...)` — which is the "outcome" this AC refers to, giving CLI exit code 1 via the existing `main_async` `0 if result.success else 1` — and logs `publish_store_unavailable` at WARNING with `exc_info=True` (the existing log call, currently followed by the fail-open fallback, is kept but now precedes a raise instead of a `return`). This is caught inside `execute()`, not raised out of it, so `web/service.py`'s `/publish` call site (which only reads `result.success`/`result.publish_results`/`result.error` off the returned `WorkflowResult`) gets a normal `PublishResponse` with `any_success=False` and an empty `results` dict — not a 500 — with no change needed at that call site
- AC9: Given no publish store is configured, when the run executes, then the file-state path behaves exactly as before

## Implementation Notes

- Mirror `services/storage.py:56-63` for the predicate; add a comment naming the wrap order.
- Mirror `services/usage_meter.py` for the fire-and-forget drain.
- Four sub-issues, four PRs: #183, #184, #185, #186. Each carries its own failing test first.
- AC8 is a deliberate fail-closed change; the PR body must say so and name the exit code (1, via
  the existing `0 if result.success else 1` in `main_async` — no new exit code is introduced).

### Hardening decisions (pinned so implementation doesn't have to invent them)

- **#183 (predicate + except clauses, AC1–AC3)**: `_is_transient_s3_error` unwraps
  `StorageError.__cause__` exactly like `_is_retryable_dropbox_error` does. Separately, widen the
  `except ClientError as exc:` to `except (ClientError, EndpointConnectionError,
  BotoConnectionError) as exc:` on the ten `@retry`-decorated legacy per-image methods
  (`list_images`, `list_images_with_hashes`, `download_image`, `get_temporary_link`,
  `get_file_metadata`, `write_sidecar_text`, `download_sidecar_if_exists`, `archive_image`,
  `move_image_with_sidecars`, `delete_file_with_sidecar`) — those are what AC1–AC3 test, and the
  predicate fix alone does not satisfy AC3 on them, because today those connection errors aren't
  caught at all and leak raw. The six `#96` object-level methods (`list_objects`, `put_object`,
  `head_object`, `exists`, `delete_object`, `move_object`) have no `@retry` decorator and are
  **out of scope** for this item — `head_object` in particular has the same latent leak against
  its own "never raises" docstring, but that's a separate follow-up, not part of #183.
  For fast, deterministic retry tests, extract the ten near-duplicate `@retry(...)` decorator
  instantiations already on `ManagedStorage` methods into one shared module-level decorator
  (mirroring `_dropbox_retry` in `storage.py`), with the wait callable behind a module-level name
  (mirroring `_dropbox_wait`) so a `_fast_retries` autouse fixture can monkeypatch it to `0.0`,
  exactly like `tests/test_storage_error_paths.py::_fast_retries`.
- **#184 (Delimiter, AC4)**: add `Delimiter="/"` to the two `paginator.paginate(...)` calls in
  `list_images`/`list_images_with_hashes`. `_is_immediate_child_object_key` stays as the
  belt-and-suspenders client-side filter (scope explicitly keeps it); it costs nothing extra since
  `Delimiter` already means the paginator's `Contents` never contains nested keys.
- **#185 (meter, AC5–AC6)**: `StorageOpsMeter.flush()` becomes: drain the counter synchronously
  (`self._storage.drain_ops_count()`, already fast and lock-protected), append the batch to the
  existing `_pending`-style bookkeeping, and ensure a background task is running that pops one
  batch at a time and posts it via `_post_batch` wrapped in `asyncio.wait_for(timeout=5.0)` (new
  module constant `_DRAIN_ATTEMPT_TIMEOUT_SECONDS = 5.0`) — `flush()` itself awaits nothing that
  can block on the network, so it returns in the same call regardless of orchestrator health. Add
  a new `aclose()` method (mirroring `UsageMeter.aclose()`) that cancels the periodic task if
  running and then attempts the remaining pending batches with a bounded total deadline (new
  module constant `_ACLOSE_DEADLINE_SECONDS = 10.0`), logging `storage_ops_meter_undrained_queue`
  with the remaining count if the deadline is hit — never raises. `stop_periodic_flush()` keeps
  its name (both call sites — `core/workflow.py` and `web/service.py` — are unchanged) but its body
  becomes `await self.aclose()`. Expose `pending_batch_count() -> int` returning `len(self._pending)`
  — a batch is popped from `_pending` **only after** `_post_batch` returns `True`, so the count
  stays accurate (non-zero) even while an attempt is in flight, not just when the drain loop is at
  rest between attempts; this is what makes AC5's "the meter still holds the undelivered batch"
  assertion deterministic against a hung `post_usage` rather than a race. The drain task makes one
  pass over a snapshot of `_pending` taken at entry and then exits (unlike `UsageMeter._drain_loop`,
  which loops forever) — `flush()` restarts it if it isn't running, matching `_ensure_drainer`'s
  already-running check. Within that pass, a batch whose attempt fails is **kept** (with its
  original idempotency key) and the pass moves on to the next batch, so one permanently failing
  batch cannot head-of-line-block the batches behind it. The pass must **not** restart itself while
  `_pending` is non-empty: that is what stops a dead orchestrator from being hot-spun with no
  backoff. Net effect: the whole queue drains in one go while the orchestrator is healthy, and
  exactly one attempt per pending batch is made while it is down. In
  `core/workflow.py`'s `execute()` `finally` block, move the `pending_leases` release block (and
  its `asyncio.shield`) so it runs before the `meter.flush()` call — before this item it was the
  reverse.
- **#186 (Postgres + claim budget, AC7–AC9)**: see the AC7/AC8 field names above. `init_db()`
  passes `connect_args={"timeout": settings.db_connect_timeout_seconds, "command_timeout":
  settings.db_command_timeout_seconds}` to `create_async_engine`. `_claim_publish_targets` wraps
  its `store.posted_platforms(...)` + `store.acquire_lease(...)` pair in one
  `asyncio.wait_for(..., timeout=self._settings.publish_claim_timeout_seconds)`; a `TimeoutError`
  is handled by the same `except` that catches `acquire_lease` raising directly (both become
  `PublishStoreUnavailableError`). At the default 10s claim budget, this outer timeout fires well
  before asyncpg's 30s `command_timeout` could — add a one-line comment at the `wait_for` call
  noting that `command_timeout` still matters for `CaptionStore`/other DB calls not wrapped in a
  claim budget, so a future reader doesn't "simplify" the apparent redundancy away.

## Risks

- A background meter drain that dies silently would under-bill; the drain task must log its own failure and `aclose()` must surface an undrained queue.
- AC8 changes behaviour on a store outage from "publish anyway" to "abort"; that is what #85 intended, but it must be visible in the CLI exit code and logs.

## Success Metrics

- Zero cron failures attributable to a single R2 throttle after deploy.
- LIST ops per cron run equal to one for a root under 1,000 live keys.
- p99 analyze latency unchanged during a simulated orchestrator outage.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issues [#183](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/183), [#184](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/184), [#185](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/185), [#186](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/186)
- [PUB-045: R2 Storage Ops Metering](PUB-045_storage-ops-metering.md) — the meter this makes non-blocking
- [PUB-024: Managed Storage Adapter](PUB-024_managed-storage-adapter.md) — the retry layer this repairs
- Prior fixes #93 (single retry layer), #132 (Dropbox predicate), #139 (lease expiry)

## Change Log

- 2026-09-21 — Shipped and archived. PR [#214](https://github.com/dhirmadi/SocialMediaPythonPublisher/pull/214),
  merge commit `f05a1d6`, seven commits (one per sub-issue #183-#186, plus docs and the review
  response). Gates at merge: ruff format and lint clean, mypy clean over 64 source files,
  1752 passed / 1 skipped, coverage 92.48% (gate 85); per-module: `storage_ops_meter.py` 100%,
  `db/__init__.py` 100%, `core/exceptions.py` 100%, `runtime_settings.py` 99%, `core/workflow.py`
  94%, `managed_storage.py` 91%. All 16 handoff test names present verbatim. Review follow-ups:
  the drain-deadline under-billing case is tracked as
  [#215](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/215); the agent-memory and
  push-permission commit was split out to PR
  [#216](https://github.com/dhirmadi/SocialMediaPythonPublisher/pull/216). Handoff deleted per the
  spec-format lifecycle; plan and summary kept here as the implementation record.

- 2026-09-21 — Implemented (all four sub-fixes); PR #214. Tightened the #185 drain-loop
  wording: the hardened text said the task "loops while `_pending` is non-empty and then exits",
  which taken literally hot-spins a dead orchestrator with no backoff. Replaced with the shipped
  contract — one bounded pass over a snapshot taken at entry, keeping (not head-of-line-blocking
  on) a failed batch. A first implementation that stopped at the first failure was caught in review
  as a regression against the pre-PUB-047 `flush()`, which attempted every pending batch. See
  `PUB-047_summary.md` for the full deviation list.

- 2026-09-21 — Spec hardened for Claude Code handoff. Pinned the previously-open naming/mechanism
  decisions (new `RuntimeSettings` fields, `PublishStoreUnavailableError`, `StorageOpsMeter`
  internals, exact except-clause widening for AC3) directly into the ACs and Implementation Notes
  so no design choice is left to the implementer. See `PUB-047_summary.md`.
