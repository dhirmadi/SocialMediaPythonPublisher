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

- **Drain posts get a per-call request timeout of 15.0 s**, held as a new named constant
  `_DRAIN_POST_TIMEOUT_SECONDS = 15.0` in `storage_ops_meter.py`, alongside
  `_DRAIN_ATTEMPT_TIMEOUT_SECONDS`. A bare literal is not acceptable — AC4 needs a constant to read,
  the same way the invariant it replaces read `_DRAIN_ATTEMPT_TIMEOUT_SECONDS` directly rather than
  a copy of it.
- **The override is a new `timeout: float | None = None` keyword on `post_usage`**, threaded
  through `_request_with_retry` to `self._client.request(..., timeout=...)`. It is **independent
  of, not folded into, `retry: RetryConfig`** — `RetryConfig` is backoff/attempt-count policy
  ("Exponential-backoff parameters shared by every orchestrator request"); a per-request timeout is
  an orthogonal axis, and every other call site already constructs a bare `RetryConfig()`, so adding
  a timeout field there would be a change those callers don't need.
- **Critical plumbing requirement**: when `timeout` is `None` (every caller except the drain path
  today), `_request_with_retry` must pass `httpx.USE_CLIENT_DEFAULT` to `self._client.request(...)`,
  **never a bare `None`**. `httpx` treats `timeout=None` as *no timeout at all*, not *use the
  client's configured default* — passing `None` through unconditionally would silently strip the
  5.0 s budget from `get_runtime_by_host` and `resolve_credentials`, which is the opposite of what
  AC2 requires and strictly worse than today's behavior. This is the single highest-risk detail in
  this item and must not be left to the implementer to discover via a failing test.
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

`test_drain_attempt_timeout_exceeds_client_timeout_and_fits_aclose_budget`'s name and docstring
("fits inside the drain deadline, which fits aclose()") assert exactly the claim this item removes
— both must be rewritten, not just the assertion body, so the test's name stops documenting an
invariant that no longer holds. AC5's new "surfaces an undrained queue" behavior is a distinct
scenario (an `aclose()`-level cancellation, not a constants-only check) and belongs in its own new
test function, not appended to the renamed one.

## Scope

**In scope:**
- A per-call `timeout: float | None = None` keyword on `post_usage` (new, independent of the
  existing `retry` override), threaded through `_request_with_retry` (also `timeout: float | None
  = None`) to the `self._client.request(...)` call site, which resolves `None` to
  `httpx.USE_CLIENT_DEFAULT` there — the kwarg's own default stays `None` end-to-end; only the final
  call site translates it
- The named constant `_DRAIN_POST_TIMEOUT_SECONDS = 15.0` in `storage_ops_meter.py`
- `StorageOpsMeter._post_batch` passing `timeout=_DRAIN_POST_TIMEOUT_SECONDS`;
  `_DRAIN_ATTEMPT_TIMEOUT_SECONDS` 8.0 → 18.0
- Updating the PUB-061 AC4 assertion per the revision above

**Out of scope:**
- The shared `timeout_seconds=5.0` default and every interactive caller
- `_ACLOSE_DEADLINE_SECONDS`, the 12-batch `_pending` cap, the idempotency-key scheme
- The single-attempt retry decision from PUB-061 — drain posts still make exactly one attempt
- Making the values configurable via `RuntimeSettings`; the two named module constants
  (`_DRAIN_POST_TIMEOUT_SECONDS`, `_DRAIN_ATTEMPT_TIMEOUT_SECONDS`) are enough until there is
  evidence a deployment needs to differ

## Acceptance Criteria

- AC1: Given a drain post, when `post_usage` is called by `StorageOpsMeter._post_batch`, then it
  passes `timeout=_DRAIN_POST_TIMEOUT_SECONDS` (the named constant, 15.0 s), and a transport
  asserting on the effective per-request timeout sees 15.0 rather than the client's configured
  default
- AC2: Given an interactive call (`get_runtime_by_host`, `resolve_credentials`) and a `post_usage`
  called without the override, when it runs, then the client's 5.0 s default still applies — no
  caller inherits the drain budget, and the override's `None` default must resolve to
  `httpx.USE_CLIENT_DEFAULT` at the `self._client.request(...)` call site, not a bare `None` (a bare
  `None` disables the timeout entirely instead of preserving the client default — this is the
  specific regression this AC exists to block)
- AC3: Given an orchestrator that answers successfully after longer than the old 5.0 s request
  timeout but inside the new 15.0 s one, when the drain task runs, then the batch is delivered and
  `len(meter._pending) == 0` — matching the private-state convention every other test in
  `test_storage_ops_meter.py` already uses (there is no `pending_batch_count()` method; #286 deleted
  it as a test-only wrapper and `test_storage_ops_meter_has_no_alias_or_test_only_wrappers` asserts
  it stays gone)
- AC4: Given the constants, when they are read, then `_DRAIN_POST_TIMEOUT_SECONDS` (15.0) is
  strictly less than `_DRAIN_ATTEMPT_TIMEOUT_SECONDS` (18.0) — the outer `wait_for` remains a
  backstop for a hung attempt, never the routine limiter for a merely-slow one. (The client's
  unrelated shared default, 5.0, is untouched by this item and is not part of this invariant — drain
  posts no longer use it once the override is in place.) The PUB-061 upper bound against
  `_ACLOSE_DEADLINE_SECONDS` is **removed**, per PUB-061's own Out-of-scope note, which flagged this
  exact follow-up as the reason it declined to raise the request timeout itself
- AC5: Given a batch whose attempt outlives `_ACLOSE_DEADLINE_SECONDS` during `aclose()`, when the
  close budget fires, then `aclose()` returns without raising, the batch is retained with its
  original idempotency key, and `storage_ops_meter_undrained_queue` is logged with the remaining
  count — this is what makes dropping the upper bound safe, so it is pinned by a test
- AC6: Given a hung `post_usage`, when the drain task runs, then it is still abandoned at
  `_DRAIN_ATTEMPT_TIMEOUT_SECONDS` and `storage_ops_drain_attempt_timeout` is logged (PUB-047 AC5
  and PUB-061 must not regress)

## Implementation Notes

- `timeout: float | None = None` is a new keyword on `post_usage`. `_request_with_retry` gains the
  identical new parameter — `timeout: float | None = None`, its own argument alongside the existing
  `retry: RetryConfig | None = None`, not derived from it — and applies it at
  `self._client.request(..., timeout=timeout if timeout is not None else httpx.USE_CLIENT_DEFAULT)`.
  Prefer passing the value through rather than mutating client state.
- **Do not pass a bare `None` to `httpx.AsyncClient.request(timeout=...)`.** Omitting the kwarg or
  passing `httpx.USE_CLIENT_DEFAULT` preserves the client's configured `timeout_seconds`; passing
  `None` disables the timeout for that request entirely. Every non-drain call site must resolve to
  one of the former, never the latter. This is AC2's actual regression target — write the test
  against the real `_request_with_retry` default path, not just against the drain path's override.
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
  constraint, and its **Out-of-scope section explicitly predicted this item**: "Whether drain posts
  deserve a longer per-request timeout is a separate question, tracked in its own issue [that issue
  is #218, this item] — changing it here would also force re-deriving the 8.0 s deadline (AC4)."
  This item executes that anticipated follow-up; the AC4 revision is not new scope, it is PUB-061
  cashing a check it wrote for itself
- [PUB-047: Reliability Batch](archive/PUB-047_reliability-batch.md) — introduced the drain task
- [PUB-045: R2 Storage Ops Metering](archive/PUB-045_storage-ops-metering.md) — the meter itself

## Change Log

- 2026-10-13 (2) — Second `architect-reviewer` pass, run fresh against the already-hardened spec to
  verify the first round of fixes rather than trust the spec's own claim they worked. Found one new
  **blocking** defect the first pass missed: AC3 asserted `pending_batch_count()` returns 0, but
  that method does not exist — #286 deleted it as a test-only wrapper, and
  `test_storage_ops_meter_has_no_alias_or_test_only_wrappers` asserts it stays deleted. AC3 now
  reads `len(meter._pending) == 0`, matching every other test in the file. Also fixed three
  cosmetic residues from the first pass: Scope's out-of-scope bullet still said "a literal" after
  the literal became a named constant; Scope's "defaulting to `USE_CLIENT_DEFAULT` when unset" could
  be misread as `post_usage`'s own kwarg default (it is `None`; only the final `_client.request()`
  call site resolves to `USE_CLIENT_DEFAULT`); and the AC4 test being revised keeps a name/docstring
  that assert the exact invariant this item removes — now called out explicitly as needing rewrite,
  with AC5 pinned to its own new test rather than appended to the renamed one.
- 2026-10-13 (1) — Hardened after an `architect-reviewer` pass on PR #222. Three gaps closed: (1) the
  override is now pinned as a new `timeout` keyword independent of `RetryConfig`, with an explicit
  warning against passing a bare `None` to `httpx`'s `timeout=` (which disables timeouts entirely
  rather than falling back to the client default — this would have silently broken AC2 for every
  interactive caller); (2) 15.0 s is now a required named constant
  (`_DRAIN_POST_TIMEOUT_SECONDS`), making AC4's drain-margin clause testable by reading the
  constant rather than hardcoding a copy of the literal; (3) AC4's decorative client-default clause
  is dropped in favor of the single invariant that matters (`_DRAIN_POST_TIMEOUT_SECONDS` <
  `_DRAIN_ATTEMPT_TIMEOUT_SECONDS`), and the Related section now cites PUB-061's own Out-of-scope
  note, which predicted this exact follow-up.
- 2026-09-21 — Written from #218. The timeout value and the revision of PUB-061's AC4 upper bound
  are pinned here rather than left to implementation, because the latter requires changing an
  existing assertion and that must be a spec decision, not an implementer's convenience.
