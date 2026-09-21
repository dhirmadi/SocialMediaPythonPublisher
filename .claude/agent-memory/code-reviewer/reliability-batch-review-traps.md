---
name: reliability-batch-review-traps
description: PUB-047/PUB-061 traps — flush()'s sleep(0) is load-bearing for 6 legacy meter tests, _drain_pending makes one keep-on-failure pass, wait_for around the whole claim can orphan a server-side lease, drain deadline sits between the client timeout and the aclose budget
metadata:
  type: project
---

PUB-047 (#183–#186) review findings worth carrying forward.

**Why:** these are non-obvious consequences of designs the spec pinned, easy to
re-litigate or re-break in PUB-054 (selection through the store) and any future
metering work.

**How to apply:** when reviewing `services/storage_ops_meter.py`,
`core/workflow.py::_claim_publish_targets`, or `services/managed_storage.py`:

- `StorageOpsMeter.flush()` ends with `await asyncio.sleep(0)`. That single yield is
  load-bearing: removing it fails 6 pre-existing tests that do `await meter.flush()`
  then `post_usage.assert_awaited_once()` (verified by mutation). It works because
  `asyncio.wait_for` + an `AsyncMock` completes the drain task's first step inline.
  It does NOT reintroduce blocking — the AC5 hung-orchestrator test passes with and
  without it. Any future test that calls `flush()` and immediately asserts on
  `post_usage` is relying on this yield, not on the drain task being awaited.
- `_drain_pending()` makes ONE pass over a snapshot of `_pending` taken at entry, and a
  batch whose attempt fails is KEPT (original idempotency key) while the pass moves on
  to the next. Two rules are load-bearing and pull against each other: the keep-and-
  continue is what stops one poison batch (e.g. a 400) head-of-line-blocking the queue
  until the 12-batch cap evicts it; the never-restart-while-pending is what stops a dead
  orchestrator being hot-spun with no backoff. A "fix" to either usually breaks the
  other. (Correction: an earlier draft of this note said the pass returns at the first
  failure. That WAS the first implementation and the #214 review caught it as a
  regression vs. the pre-PUB-047 loop; the shipped code continues past a failure.)
- `_claim_publish_targets` wraps `posted_platforms` + `acquire_lease` in ONE
  `asyncio.wait_for`. If the timeout fires after the server actually granted the
  lease, `owned_tokens` is lost, `pending_leases` stays empty, and the row stays
  leased until the #139 TTL. Fail-closed by design; not a leak to "fix" locally.
- `_managed_retry` is one shared module-level `retry(...)` for ten methods. tenacity
  builds a fresh `AsyncRetrying` per decoration, so no shared state — but NO test
  pins `stop_after_attempt(3)`/`wait_exponential(1,1,8)`, because the wait is
  monkeypatched to 0.0. A budget change would pass the suite silently.
- The three inner `except ClientError` handlers (404-tolerant sidecar reads in
  `download_sidecar_if_exists`/`archive_image`/`move_image_with_sidecars`) must stay
  narrow; widening them would swallow connection errors that the outer widened
  handler needs to turn into a retryable `StorageError`.

PUB-061 (#215) then changed the drain's timing, in the same file:

- Drain posts pass `RetryConfig(max_attempts=1)`, so the client's 3-attempt retry is
  deliberately OFF for them — the meter's own `_pending` retry is the only layer. Every
  other `post_usage`/`_request_with_retry` caller keeps the default three attempts; a
  regression test pins that (3 transport calls, 2 backoff sleeps).
- `_DRAIN_ATTEMPT_TIMEOUT_SECONDS` (8.0) must stay strictly between the client's
  per-request `timeout_seconds` (5.0) and `_ACLOSE_DEADLINE_SECONDS` (10.0). A test
  asserts it and reads the client default via `inspect.signature`, so moving either
  constant fails loudly. Don't round 8.0 to something "neater".
- The binding constraint on a real drain post is now httpx's 5 s request timeout, NOT
  the 8 s deadline. A slower response fails as `OrchestratorUnavailableError`, not as a
  drain timeout — PUB-061's spec originally claimed otherwise and was corrected. Whether
  drain posts need a longer request timeout is issue #218.
- Jitter lives in `_with_jitter(delay_ms, policy)`, not inside `_sleep`, because three
  test helpers stub `_sleep` as a bound-less SINGLE-argument function; giving `_sleep` a
  second parameter raises `TypeError` in those tests. Widen the stubs first if you ever
  need the policy in there.

Related: [[lease-expiry-review-traps]], [[layering-guard-review-traps]],
[[runtime-settings-injection-traps]], [[mutation-check-review-technique]].
