# PUB-061 — Storage-Ops Drain Deadline: Implementation Summary

**Status:** Implementation Complete
**Date:** 2026-09-21
**Issue:** [#215](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/215)

## Files Changed

### Source
- `publisher_v2/src/publisher_v2/config/orchestrator_client.py` — `_request_with_retry` and
  `post_usage` take `retry: RetryConfig | None = None`, resolved as `policy = retry or self._retry`.
  Jitter is hoisted out of `_sleep` into a policy-aware `_with_jitter(delay_ms, policy)` static
  helper applied at both call sites (review nit).
- `publisher_v2/src/publisher_v2/services/storage_ops_meter.py` — new module constant
  `_SINGLE_ATTEMPT_RETRY = RetryConfig(max_attempts=1)` passed by `_post_batch`;
  `_DRAIN_ATTEMPT_TIMEOUT_SECONDS` 5.0 → 8.0 with a comment naming the invariant.

### Tests
- `publisher_v2/tests/config/test_orchestrator_usage.py` — single-attempt override, default-unchanged
  guard, and the two jitter-policy tests.
- `publisher_v2/tests/test_storage_ops_meter.py` — `TestSlowButAliveOrchestrator` (3 tests).

## Acceptance Criteria

| AC | Test | Result |
|----|------|--------|
| AC1 single attempt | `test_post_usage_single_attempt_calls_transport_once_without_backoff` | PASS |
| AC1 default unchanged | `test_post_usage_without_override_keeps_three_attempt_behaviour` | PASS (regression guard) |
| AC1 meter wiring | `TestSlowButAliveOrchestrator::test_drain_post_uses_single_attempt_retry_override` | PASS |
| AC2 | `TestSlowButAliveOrchestrator::test_slow_but_alive_post_usage_batch_is_delivered_not_timed_out` | PASS — **see the scope correction below** |
| AC3 | pre-existing `TestDrainLoopBackoffSemantics::test_drain_attempt_timeout_is_bounded_and_logged`, `TestAclose::test_aclose_deadline_logs_undrained_queue_and_never_raises` | PASS (unmodified) |
| AC4 | `TestSlowButAliveOrchestrator::test_drain_attempt_timeout_exceeds_client_timeout_and_fits_aclose_budget` | PASS |
| AC5 | pre-existing `TestPerFlushIdempotencyKeys::test_failed_flush_retries_same_batch_with_same_key` | PASS (unmodified) |
| Review nit | `test_post_usage_per_call_jitter_disabled_uses_deterministic_backoff`, `test_post_usage_default_policy_still_applies_jitter` | PASS |

No handoff doc exists for this item, so no exact-test-name contract applies; the names above are
the mapping of record.

## The scope correction (important)

The first draft of this spec claimed a ~6 s orchestrator response would be delivered once the
deadline was raised. **That was wrong, and the review caught it.** `OrchestratorClient` builds
`httpx.AsyncClient(timeout=timeout_seconds)` with `timeout_seconds=5.0`, so a 6 s response raises
`ReadTimeout` → `httpx.RequestError` at ~5 s no matter what the outer deadline is. The claim that
the pre-PUB-047 inline `flush()` "would have waited and succeeded" was wrong for the same reason.

What this item actually fixes:

- **The stacked retry layers.** One `post_usage` could span 3 × 5 s plus backoff (~16 s), so no
  sane per-attempt deadline could contain it and *every* attempt against a degraded orchestrator
  was cancelled mid-retry. Drain posts now make one client attempt; the meter's own `_pending`
  retry (with the original idempotency key) is the only retry layer — the #93/#84/#88 principle.
- **The 4–5 s band** that used to race the old 5.0 s deadline and lose to overhead.

What it does **not** fix: responses slower than the client's 5 s request timeout. Those now fail as
`OrchestratorUnavailableError` rather than as a drain timeout. Whether drain posts deserve a longer
per-request timeout is tracked as [#218](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/218).

AC2's test drives a mocked `post_usage`, so it pins the meter's deadline, not a real HTTP response
time. That is why the original overclaim was easy to miss from the test name alone.

## Quality Gates

- Format, lint, mypy: clean
- Tests: **1759 passed**, 1 skipped
- Coverage: `storage_ops_meter.py` 100%, `orchestrator_client.py` **82% → 86%**, overall 92.5% (gate 85)

## Subagent Verdicts

- `code-reviewer`: **PASS WITH NITS** — mutation-verified that 4 of 5 new tests fail against unfixed
  source; confirmed no PUB-047 regression, clean blast radius (4 `_request_with_retry` call sites,
  only `post_usage` forwards `retry`; `usage_meter.py` unaffected), and raised the scope correction
  above plus the `_sleep` jitter trap, both actioned.
- `security-auditor`: **N/A** — no web, auth, secret or credential-loading files touched.

## Notes

- **Why jitter moved instead of `_sleep` gaining a parameter.** The obvious fix — `_sleep(self,
  delay_ms, policy=None)` — is impossible against the current tests: three helpers
  (`test_orchestrator_usage.py:19,231`, `test_orchestrator_credentials.py:27`) stub `_sleep` with a
  strictly one-argument function assigned to the *instance*, so there is no `self` binding and a
  second argument raises `TypeError`. Hoisting jitter into `_with_jitter` keeps `_sleep`'s arity and
  is arguably the better separation anyway. A future item needing the policy inside `_sleep` must
  widen those stubs first.
- `_SINGLE_ATTEMPT_RETRY` is a shared module constant; `RetryConfig` is frozen with slots, so there
  is no shared-mutable-state hazard.
- Second-order effect of the 8.0 s deadline inside the unchanged 10 s `aclose()` budget: a close can
  now carry at most one hung attempt to its deadline instead of two. Intended — the close budget was
  pinned out of scope.
- `storage_ops_meter.py` promotes `RetryConfig` to a runtime `publisher_v2.config` import. The
  layering guard only forbids `services → web`, and `services → config` has five precedents.
- Stale reviewer memory: `.claude/agent-memory/code-reviewer/reliability-batch-review-traps.md`
  states `_drain_pending()` returns at the first failed batch. The shipped code continues past a
  failure and keeps the batch (fixed during the #214 review), so that note is out of date.
