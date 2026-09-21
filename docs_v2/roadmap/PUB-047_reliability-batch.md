# PUB-047: Reliability Batch — R2 Retries, Listing Cost, Meter Flush, Postgres Bounds

| Field | Value |
|-------|-------|
| **ID** | PUB-047 |
| **Category** | Foundation |
| **Priority** | P0 |
| **Effort** | S |
| **Status** | Proposal |
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
- AC3: Given a client that raises `EndpointConnectionError` on every attempt, when any storage method is called, then a `StorageError` is raised, not a botocore exception
- AC4: Given a fake paginator recording its kwargs, when `list_images` or `list_images_with_hashes` runs, then `Delimiter="/"` is passed and a root with N live keys and any number of archived keys counts one page per 1,000 live keys
- AC5: Given an orchestrator that never responds, when analyze runs through the real app, then the response returns in under one second and the meter's pending queue holds the batch
- AC6: Given a workflow run with twelve pending meter batches and a failing orchestrator, when the run finishes, then the lease is released before any meter call and a cancellation delivered during metering still releases the lease
- AC7: Given the engine is created, when its kwargs are inspected, then `connect_args` carries both timeouts from `RuntimeSettings`
- AC8: Given a publish store whose `acquire_lease` raises or hangs past the claim budget, when the run reaches the claim, then the run aborts with outcome `publish_store_unavailable`, publishes nothing, and logs the event with `exc_info`
- AC9: Given no publish store is configured, when the run executes, then the file-state path behaves exactly as before

## Implementation Notes

- Mirror `services/storage.py:56-63` for the predicate; add a comment naming the wrap order.
- Mirror `services/usage_meter.py` for the fire-and-forget drain.
- Four sub-issues, four PRs: #183, #184, #185, #186. Each carries its own failing test first.
- AC8 is a deliberate fail-closed change; the PR body must say so and name the exit code.

## Risks

- A background meter drain that dies silently would under-bill; the drain task must log its own failure and `aclose()` must surface an undrained queue.
- AC8 changes behaviour on a store outage from "publish anyway" to "abort"; that is what #85 intended, but it must be visible in the CLI exit code and logs.

## Success Metrics

- Zero cron failures attributable to a single R2 throttle after deploy.
- LIST ops per cron run equal to one for a root under 1,000 live keys.
- p99 analyze latency unchanged during a simulated orchestrator outage.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issues [#183](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/183), [#184](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/184), [#185](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/185), [#186](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/186)
- [PUB-045: R2 Storage Ops Metering](archive/PUB-045_storage-ops-metering.md) — the meter this makes non-blocking
- [PUB-024: Managed Storage Adapter](archive/PUB-024_managed-storage-adapter.md) — the retry layer this repairs
- Prior fixes #93 (single retry layer), #132 (Dropbox predicate), #139 (lease expiry)
