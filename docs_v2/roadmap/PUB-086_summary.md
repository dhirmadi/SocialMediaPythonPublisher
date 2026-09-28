# PUB-086 — Release Leases Claimed Before a Cancellation: Implementation Summary

**Status:** Implementation Complete
**Date:** 2026-09-28

## Files Changed

- `publisher_v2/src/publisher_v2/db/publish_store.py`:
  - `acquire_lease(..., owned=None)` records each lease's token into the caller's mapping just before its commit. The token is withdrawn when the insert loses the race (`IntegrityError`).
  - In the re-lease and stale-reclaim branches, the token is recorded only when the conditional UPDATE hit exactly one row.
  - Race safety is unchanged.
- `publisher_v2/src/publisher_v2/core/workflow.py`:
  - `execute()` runs the claim as a task.
  - On a cancellation it waits for the bounded claim with `asyncio.wait`, which never re-raises the claim's own outcome, and does so again after every repeated cancel. It then hands every recorded token to the existing token-fenced release in `finally`, retrieves the claim's result, and re-raises the cancellation.
  - The store-unavailable path (claim timeout) now releases what the claim committed.
  - `_claim_publish_targets` passes `owned=` and records committed tokens as fence tokens on its failure path.
- `publisher_v2/tests/test_workflow_partial_publish.py`:
  - Six new tests.
  - `_LeaseCommitGate`, which holds the claim right after the real `AsyncSession.commit` of the first `leased` row.
  - `_MarkRecorder` and a fenced-release assertion helper.
- `publisher_v2/tests/test_workflow_lease_meter_order.py`: the fake `_RecordingStore.acquire_lease` accepts `owned` (AC4). No assertion changed.
- `docs_v2/roadmap/PUB-054_publish-state-integrity.md` and `README.md`: cross-reference and index row.

## Acceptance Criteria

- [x] AC1 — cancelling right after a lease commit leaves no `leased` row (test: `test_cancel_right_after_a_lease_commit_releases_it`)
- [x] AC2 — every committed lease is released with its own token, and another run's row is untouched (test: `test_cancel_mid_claim_releases_every_committed_lease`)
- [x] AC3 — `CancelledError` is still raised (test: `test_cancel_during_claim_still_raises_cancelled`)
- [x] AC6 — a second cancel still releases (test: `test_second_cancel_during_claim_still_releases_committed_leases`)
- [x] AC7 — a claim timeout after a commit releases it, fenced by the lease token (test: `test_claim_timeout_after_a_commit_releases_it`)
- [x] AC8 — a cancel followed by a claim timeout releases the leases and raises `CancelledError`, not `PublishStoreUnavailableError` (test: `test_cancel_then_claim_timeout_releases_and_raises_cancelled`)
- [x] AC4 — the existing lease, fencing and cancellation tests pass with unchanged assertions
- [x] AC5 — the PR body carries `Closes #315`

## Test Results

The full suite gives 2095 passed, 2 skipped, 27 deselected and 0 failed, including under `-W error::pytest.PytestUnraisableExceptionWarning`. The 8 cancel and claim-timeout tests passed 20 of 20 random-order runs.

Mutation checks: each fix step has a mutant that a named test catches:

| Mutant | Caught by |
|---|---|
| Single shield instead of the re-wait loop | AC6 |
| `shield` in the loop instead of `asyncio.wait` | AC8 |
| Token recorded after the commit | AC7 |
| No fence tokens on the failure path | AC7 and AC8 ("unfenced mark") |
| No handoff on the cancel path | AC1, AC2 and AC6 |
| No re-raise | AC1, AC2, AC3 and AC6 |

## Quality Gates

- Format: ✅
- Lint: ✅
- Type check: ✅ (63 files)
- Tests: 2095 passed, 0 failed
- Coverage: 93.59% overall; `core/workflow.py` 96%, `db/publish_store.py` 97%

## Subagent Verdicts

- `code-reviewer`: PASS WITH NITS, twice. Round 1 raised W1: nothing pinned that the release after a timeout is token-fenced. AC7 was tightened to cover this, and a test now asserts it. Round 2's remaining nits are left as is:
  - N-a: the handler's own fence-token update matters only when the claim task itself is cancelled.
  - N-b: AC8 needs the first commit to land within the 1 s claim budget. If it doesn't, the test fails loudly rather than passing falsely.
  - N-c: fencing is pinned by AC7 and AC8, not AC2.
- `security-auditor`: BLOCKED, then PASS WITH NITS.
  - The blocker: awaiting `shield(claim)` in the re-wait loop let the claim's `PublishStoreUnavailableError` escape the cancel handler before the leases were handed off, so they were stranded and the cancellation was lost. AC8 was added and the handler now uses `asyncio.wait`.
  - Remaining nit, left as is: a non-store-unavailable exception from the claim could replace the cancellation. `_claim_publish_targets` converts every `Exception` raised during the claim, so this is unreachable.
  - The auditor confirmed that a token recorded for a commit that never landed matches no row under the fenced `mark`, so it can never release another run's lease.

## Linked Issues

- #315 — closed by this PR (`Closes #315`)

## Notes

- Cancelling now waits for the claim, whose length is capped. Shutdown can therefore overrun by up to `publish_claim_timeout_seconds` (10 s by default), plus the driver's unwind time, which is bounded by `db_command_timeout_seconds`. The Change Log records this.
