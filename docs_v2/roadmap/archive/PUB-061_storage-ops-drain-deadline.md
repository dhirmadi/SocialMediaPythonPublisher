# PUB-061: Storage-Ops Drain Deadline — Stop Under-Billing a Slow-but-Alive Orchestrator

| Field | Value |
|-------|-------|
| **ID** | PUB-061 |
| **Category** | Foundation |
| **Priority** | P2 |
| **Effort** | XS |
| **Status** | Done |
| **Dependencies** | PUB-047 (shipped — made the drain non-blocking) |
| **GitHub Issue** | [#215](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/215) |

## User Story

As a platform operator, I want R2 storage-op batches to reach the orchestrator even when it is
responding slowly, so that a tenant is billed for the operations they actually used.

## Problem

PUB-047 (#185) made `StorageOpsMeter.flush()` non-blocking by moving the POST to a background
drain task, bounding each attempt with
`asyncio.wait_for(self._post_batch(...), timeout=_DRAIN_ATTEMPT_TIMEOUT_SECONDS)` where the
constant is **5.0 s**.

That deadline is smaller than a single `OrchestratorClient` call. `post_usage` goes through
`_request_with_retry`, which is `max_attempts=3` (`config/orchestrator_client.py:27`) over an
`httpx.AsyncClient` built with `timeout_seconds=5.0` (`:41`), plus exponential backoff of
`base_delay_ms=250` capped at `max_delay_ms=5000` with jitter. Worst case is roughly
**3 x 5 s + backoff ~= 16 s** — more than three times the deadline that wraps it.

Consequence for a degraded orchestrator:

1. Because three attempts plus backoff cannot fit in 5 s, a drain attempt is cancelled part-way
   through its *first* retry and logs `storage_ops_drain_attempt_timeout`.
2. The batch is correctly kept in `_pending`, which grows.
3. At the 12-batch cap the oldest is dropped with `storage_ops_pending_batch_dropped`.
4. The tenant is **under-billed** for those R2 operations.

A fully hung orchestrator is still handled correctly (that is what PUB-047 AC5 pins), and a
healthy one never approaches the deadline.

### Correction (2026-09-21, from the PUB-061 review)

An earlier draft of this item claimed a response taking ~6 s would be delivered once the deadline
was raised, and that the pre-PUB-047 inline `flush()` "would have waited and succeeded". **Both
were wrong.** The client is built as `httpx.AsyncClient(timeout=timeout_seconds)` with
`timeout_seconds=5.0` (`config/orchestrator_client.py:62`), so a 6 s response raises `ReadTimeout`
→ `httpx.RequestError` at ~5 s regardless of any outer deadline; the inline flush would have
failed too.

What is genuinely broken, and what this item fixes, is the **stacked retry layers**: a single
`post_usage` can span 3 × 5 s plus backoff (~16 s), so *no* sane per-attempt deadline could contain
it, and every attempt against a degraded orchestrator was cancelled before completing. Removing
the inner retry layer means one attempt is bounded by the client's own 5 s request timeout, which
then fits comfortably inside the drain deadline. Responses slower than that request timeout remain
undelivered — see Out of scope.

## Desired Outcome

A drain attempt against an orchestrator that answers **within the client's per-request timeout**
delivers the batch instead of being cancelled by a deadline it could never have met. A hung
orchestrator still cannot block the drain task or the request path.

## Scope

**In scope:**
- A way to make a drain POST use a **single** client attempt instead of three
- `_DRAIN_ATTEMPT_TIMEOUT_SECONDS` sized to one client attempt plus a small margin
- Keeping the meter's own retry as the only retry layer for drain posts

**Out of scope:**
- `_ACLOSE_DEADLINE_SECONDS` (10.0) and the 12-batch `_pending` cap — unchanged
- The idempotency-key scheme from #92
- Retry behaviour of any other `OrchestratorClient` caller (runtime config, credential resolve)
- Making `flush()` blocking again in any form
- **Raising the client's own `timeout_seconds` (5.0).** A response slower than that still fails,
  now at the request timeout rather than at the drain deadline. Whether drain posts deserve a
  longer per-request timeout is a separate question, tracked in its own issue — changing it here
  would also force re-deriving the 8.0 s deadline (AC4).

## Decision (pinned, so implementation does not have to choose)

The issue offered two options. **Take the single-attempt one.**

Rationale: the meter already has its own retry layer — a failed batch stays in `_pending` with its
original idempotency key and is retried by the next `flush()`/`aclose()`. The client's internal
three attempts are therefore redundant *for drain posts specifically*, and they are exactly what
makes one call exceed the deadline wrapping it. Removing that inner layer is the #93/#84/#88
"single retry layer" principle applied here.

Sizing the deadline to the client's ~16 s worst case instead would leave two retry layers stacked
and make a drain attempt hold a slot for 16 s, which is worse for `aclose()`'s 10 s total budget.

## Acceptance Criteria

- AC1: Given an `OrchestratorClient` whose transport returns a retryable status, when `post_usage`
  is called with the new single-attempt option, then the transport is called **exactly once** and
  no backoff sleep occurs; called without it, the existing three-attempt behaviour is unchanged
- AC2: Given a `StorageOpsMeter` whose `post_usage` returns successfully after longer than the old
  5.0 s deadline but within the new one, when the drain task runs, then the batch is delivered and
  `pending_batch_count()` returns 0 — today it is cancelled and the batch is retained. (The test
  drives a mocked `post_usage`, so it pins the *meter's* deadline, not a real HTTP response time;
  the client's own 5 s request timeout is what bounds a real call.)
- AC3: Given a `post_usage` that never returns, when the drain task runs, then the attempt is
  still abandoned at `_DRAIN_ATTEMPT_TIMEOUT_SECONDS`, `storage_ops_drain_attempt_timeout` is
  logged, and the batch is retained with its original idempotency key (PUB-047 AC5 must not
  regress)
- AC4: Given `_DRAIN_ATTEMPT_TIMEOUT_SECONDS`, when it is read, then it is strictly greater than
  the client's per-request `timeout_seconds` and strictly less than `_ACLOSE_DEADLINE_SECONDS`, so
  one attempt fits inside the close budget
- AC5: Given the meter drains a batch, when the POST fails, then the batch keeps its original
  idempotency key for the next run exactly as before (no double-billing)

## Implementation Notes

- `RetryConfig` is a frozen dataclass; the cheapest single-attempt route is to let `post_usage`
  take an override rather than mutating shared client state — a per-call argument, not a second
  client instance, so the connection pool is shared.
- `_DRAIN_ATTEMPT_TIMEOUT_SECONDS` should be derived from or documented against the client's 5.0 s
  request timeout. A literal `8.0` with a comment naming the relationship is acceptable; a value
  above `_ACLOSE_DEADLINE_SECONDS` is not (AC4).
- The drain loop's one-pass-per-run shape and its keep-on-failure semantics are settled by PUB-047
  and must not change.

## Risks

- Dropping to one attempt means a single transient 503 defers the batch to the next flush rather
  than retrying inline. Acceptable: the periodic flush is 300 s, the cap is 12 batches, and the
  idempotency key makes the retry free.

## Success Metrics

- No `storage_ops_pending_batch_dropped` attributable to the deadline while the orchestrator is
  answering inside its 5 s request timeout. Drops caused by responses slower than that timeout
  are out of scope here and would show as `OrchestratorUnavailableError`, not as a drain timeout.

## Related

- Issue [#215](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/215)
- [PUB-047: Reliability Batch](PUB-047_reliability-batch.md) — introduced the deadline
- [PUB-045: R2 Storage Ops Metering](PUB-045_storage-ops-metering.md) — the meter itself
- Prior art: #93 (single retry layer), #132 (Dropbox predicate)

## Change Log

- 2026-09-21 — Shipped and archived. PR [#219](https://github.com/dhirmadi/SocialMediaPythonPublisher/pull/219),
  merge commit `3abe309`, closing [#215](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/215).
  Gates at merge: ruff format and lint clean, mypy clean over 64 source files, 1759 passed / 1 skipped,
  coverage 92.5% (gate 85); `storage_ops_meter.py` 100%, `orchestrator_client.py` 82% -> 86%.
  The review's two findings were both actioned before merge: the scope overclaim (recorded above as
  the Correction section) and the `_sleep` jitter trap. The residual gap — a response slower than the
  client's 5 s request timeout — remains open as
  [#218](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/218).

- 2026-09-21 — Written from the #214 review finding. The single-attempt option is pinned rather
  than left open, so implementation has no design choice to make.
- 2026-09-21 — Corrected after the implementation review: the original Problem and Desired Outcome
  overclaimed, promising delivery of a ~6 s response that httpx's 5 s request timeout makes
  impossible. Scope restated around removing the stacked retry layers, and the residual gap moved
  to Out of scope with its own issue.
