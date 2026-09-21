# PUB-062: Drain-Only Request Timeout — Deliver Batches a Slow Orchestrator Can Still Answer

| Field | Value |
|-------|-------|
| **ID** | PUB-062 |
| **Category** | Foundation |
| **Priority** | P2 |
| **Effort** | XS |
| **Status** | Not Started |
| **Dependencies** | PUB-061 (shipped — removed the inner retry layer and set the current deadline) |
| **GitHub Issue** | [#218](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/218) |

## User Story

As a platform operator, I want a storage-ops batch to reach the orchestrator even when it answers
slowly, so that a tenant is billed for what they used rather than for what happened to fit inside a
timeout sized for interactive traffic.

## Problem

`OrchestratorClient` builds one transport for every call:

```python
self._client = client or httpx.AsyncClient(timeout=timeout_seconds)   # timeout_seconds = 5.0
```

PUB-061 removed the inner retry layer for drain posts, so one drain attempt is now bounded by that
single 5 s request timeout. An orchestrator that answers in, say, 7 s therefore fails **every**
attempt: `ReadTimeout` → `httpx.RequestError` → no retry left → `OrchestratorUnavailableError`. The
batch is kept, `_pending` grows, and at the 12-batch cap the oldest is dropped with
`storage_ops_pending_batch_dropped`. Sustained latency in that band is **permanent under-billing**,
not a delay.

The 5 s value is correct for the calls it was chosen for — `get_runtime_by_host` and
`resolve_credentials` sit on the request path with a user waiting. A drain post is the opposite: a
background billing write, carrying an idempotency key (#92), that nobody is waiting on. Applying
interactive latency budgets to it is the mismatch.

## Desired Outcome

A drain post is allowed to wait materially longer than an interactive call. An orchestrator that
answers within that longer budget delivers its batch. Interactive calls are unaffected, and
shutdown does not become slower.

## Decision (pinned)

- **Drain posts get a per-call request timeout of 15.0 s.** `httpx.AsyncClient.request` accepts a
  per-request `timeout=`, so this needs no second client and no second connection pool.
- **`_DRAIN_ATTEMPT_TIMEOUT_SECONDS` rises to 18.0 s**, keeping the property that the outer
  `wait_for` is a backstop for a *hung* attempt rather than the thing that routinely cancels a live
  one.
- **`_ACLOSE_DEADLINE_SECONDS` stays 10.0 s.** Shutdown latency must not grow.

### Revising PUB-061's AC4 invariant (deliberate, not an oversight)

PUB-061 AC4 pinned `client timeout < drain deadline < aclose budget`, asserted at
`publisher_v2/tests/test_storage_ops_meter.py:500`. **The upper bound is dropped by this item**; the
lower bound stays.

Justification: `aclose()` wraps the whole drain in its own
`asyncio.wait_for(self._drain_pending(), timeout=_ACLOSE_DEADLINE_SECONDS)` and logs
`storage_ops_meter_undrained_queue` with the remaining count. A single attempt that outlives the
close budget is therefore cut short and *surfaced*, not lost — the batch stays in `_pending` with
its original idempotency key. The upper bound was a tidiness property ("one whole attempt fits
inside a close"), never a correctness one. Keeping it would force either a shorter drain timeout
than the problem needs or a longer shutdown.

This is a spec change, so the corresponding assertion is updated rather than deleted: it must keep
asserting the lower bound and gain an assertion that `aclose()` still surfaces an undrained queue
when an attempt outlives the close budget.

## Scope

**In scope:**
- A per-call request-timeout override on `post_usage`, mirroring the `retry` override PUB-061 added
- `StorageOpsMeter._post_batch` passing it; `_DRAIN_ATTEMPT_TIMEOUT_SECONDS` 8.0 → 18.0
- Updating the PUB-061 AC4 assertion per the revision above

**Out of scope:**
- The shared `timeout_seconds=5.0` default and every interactive caller
- `_ACLOSE_DEADLINE_SECONDS`, the 12-batch `_pending` cap, the idempotency-key scheme
- The single-attempt retry decision from PUB-061 — drain posts still make exactly one attempt
- Making the values configurable via `RuntimeSettings`; two module constants and a literal are
  enough until there is evidence a deployment needs to differ

## Acceptance Criteria

- AC1: Given a drain post, when `post_usage` is called by `StorageOpsMeter._post_batch`, then it
  passes a per-call request timeout of 15.0 s, and a transport asserting on the effective timeout
  sees 15.0 rather than the client default
- AC2: Given an interactive call (`get_runtime_by_host`, `resolve_credentials`) and a `post_usage`
  called without the override, when it runs, then the client's 5.0 s default still applies — no
  caller inherits the drain budget
- AC3: Given an orchestrator that answers successfully after longer than the old 5.0 s request
  timeout but inside the new 15.0 s one, when the drain task runs, then the batch is delivered and
  `pending_batch_count()` returns 0
- AC4: Given the constants, when they are read, then the client's per-request default (5.0) is
  strictly less than `_DRAIN_ATTEMPT_TIMEOUT_SECONDS` (18.0), and the drain post's own 15.0 s
  timeout is also strictly less than it — the outer `wait_for` remains a backstop, never the
  routine limiter. The PUB-061 upper bound against `_ACLOSE_DEADLINE_SECONDS` is **removed**
- AC5: Given a batch whose attempt outlives `_ACLOSE_DEADLINE_SECONDS` during `aclose()`, when the
  close budget fires, then `aclose()` returns without raising, the batch is retained with its
  original idempotency key, and `storage_ops_meter_undrained_queue` is logged with the remaining
  count — this is what makes dropping the upper bound safe, so it is pinned by a test
- AC6: Given a hung `post_usage`, when the drain task runs, then it is still abandoned at
  `_DRAIN_ATTEMPT_TIMEOUT_SECONDS` and `storage_ops_drain_attempt_timeout` is logged (PUB-047 AC5
  and PUB-061 must not regress)

## Implementation Notes

- The override should mirror `retry`'s shape: a keyword on `post_usage` threaded into
  `_request_with_retry` and applied at `self._client.request(..., timeout=...)`. Prefer passing the
  value through rather than mutating client state.
- Tests must not sleep on the real budgets. Monkeypatch the constants and scale the fake response
  delay, as `TestSlowButAliveOrchestrator` already does.
- A note belongs at `_DRAIN_ATTEMPT_TIMEOUT_SECONDS` recording *why* it no longer relates to
  `_ACLOSE_DEADLINE_SECONDS`, so the dropped invariant is not "restored" by a later reader.

## Risks

- At shutdown a single slow attempt can now consume the whole 10 s close budget, delivering fewer
  batches than before. Bounded and logged; the batches survive with their keys for the next run.
- 15.0 s is a judgement, not a measurement. If the orchestrator's real p99 on the usage endpoint is
  well below it, this is harmless; if it is above it, the same under-billing returns and the honest
  fix is on the orchestrator side. The `storage_ops_pending_batch_dropped` log remains the signal.

## Success Metrics

- No `storage_ops_pending_batch_dropped` while the orchestrator answers inside 15 s.
- Web shutdown duration unchanged (`aclose()` still bounded at 10 s).

## Related

- Issue [#218](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/218)
- [PUB-061: Storage-Ops Drain Deadline](archive/PUB-061_storage-ops-drain-deadline.md) — removed the
  inner retry layer; its Correction section explains why the 5 s request timeout became the binding
  constraint
- [PUB-047: Reliability Batch](archive/PUB-047_reliability-batch.md) — introduced the drain task
- [PUB-045: R2 Storage Ops Metering](archive/PUB-045_storage-ops-metering.md) — the meter itself

## Change Log

- 2026-09-21 — Written from #218. The timeout value and the revision of PUB-061's AC4 upper bound
  are pinned here rather than left to implementation, because the latter requires changing an
  existing assertion and that must be a spec decision, not an implementer's convenience.
