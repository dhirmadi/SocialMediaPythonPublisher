# PUB-086: Release Leases Claimed Before a Cancellation

| Field | Value |
|-------|-------|
| **ID** | PUB-086 |
| **Category** | Foundation |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Done |
| **Shipped date** | 2026-09-28 |
| **Dependencies** | — (related to PUB-054) |

**Verified:** PR [#317](https://github.com/dhirmadi/SocialMediaPythonPublisher/pull/317), merge commit `65568d3`; #315 closed; 2095 passed / 2 skipped, coverage 93.59% overall; ruff check + ruff format --check clean; mypy clean.

## User Story

As the operator, I want a cancelled publish run to release every lease it took, so that an image is not blocked from publishing for up to ten minutes because a shutdown or client disconnect landed at the wrong moment.

## Problem

#315. `WorkflowOrchestrator.execute()` claims leases through `_claim_publish_targets` → `PublishStore.acquire_lease`, which commits one `leased` row per platform in turn. The workflow learns what it owns only when the whole claim returns: `self._lease_tokens.update(...)` in `_claim_publish_targets`, then `pending_leases` in `execute()`. The `finally` releases only `pending_leases`. A cancellation delivered after one or more lease rows have committed, but before the claim returns, leaves those rows `leased` with nobody to release them. They block that image on that platform until `publish_lease_ttl_seconds` (default 600 s) expires and stale-reclaim recovers them. The same window exists on Postgres. It is reproducible every time by cancelling right after a lease commit.

## Desired Outcome

Once a lease row is committed, the run that committed it always either uses it or releases it, whether or not the run is cancelled.

## Scope

**In scope:**
- Shield the lease claim: on cancellation, let the in-flight claim (already bounded by `publish_claim_timeout_seconds`) finish, record the tokens it obtained as this run's leases, then re-raise the cancellation, so the existing `finally` releases them fenced by their tokens.
- No await point between the claim returning and the leases being visible to the `finally`.
- A repeated cancellation cannot abandon the claim: the run keeps waiting (shielded) until the bounded claim finishes.
- `acquire_lease` records each lease's token into a caller-supplied mapping just before its commit (withdrawn if the insert loses the race), so a claim cut short by its timeout still lets the run release what it committed.

**Out of scope:**
- The rest of PUB-054 (tenant-keyed state, dedup through the store, the `publishing` status).
- Changing `acquire_lease`'s per-platform semantics or its race safety.

## Acceptance Criteria

- AC1: Given a run cancelled immediately after a lease row commits (deterministically, at the commit), when `execute()` ends with `CancelledError`, then no `leased` row remains for that run's image
- AC2: Given a run cancelled while claiming several platforms, when it ends, then every lease it committed is released and no row it did not commit is touched
- AC3: Given a cancellation during the claim, when `execute()` returns control, then it still raises `CancelledError` (the cancellation is not swallowed)
- AC6: Given a second cancellation delivered while the run waits for its shielded claim to finish, when `execute()` ends, then every lease the claim committed is still released and `CancelledError` is raised
- AC7: Given the claim's own `publish_claim_timeout_seconds` expiring after one or more lease rows have committed, when the run reports the store unavailable, then the leases it committed are released, each fenced by the lease token it committed (never an unfenced mark)
- AC8: Given a cancellation delivered while the run waits for its claim, and the claim then failing (its timeout expiring after a lease row committed), when `execute()` ends, then every committed lease is released and `CancelledError` — not `PublishStoreUnavailableError` — is raised
- AC4: Given the existing lease, fencing and cancellation tests, when the suite runs, then they pass with unchanged assertions (hand-written fakes of `PublishStore` gain the new optional `owned` keyword so they keep matching its interface)
- AC5: Given this item ships, when its PR merges, then #315 is closed with `Closes #315`

## Implementation Notes

- The shielded claim may delay a cancellation by at most `publish_claim_timeout_seconds` (10 s default), which is already the claim's upper bound.
- Deterministic test hook: wrap `AsyncSession.commit` to set an `asyncio.Event` after the real commit and cancel the run on it. Use a file-backed SQLite DB (see #314's fixture fix).

## Related

- #315; [PUB-054](PUB-054_publish-state-integrity.md) (lease fencing, `publishing` status); #139 (lease release on abort)

## Change Log

- 2026-09-28 — AC6/AC7 added after implementation review: a second cancellation and the claim's own timeout are the same defect by other triggers.
- 2026-09-28 — AC4 clarified: test fakes of `PublishStore.acquire_lease` take the new `owned` keyword; tokens are recorded just before each commit (withdrawn on a lost insert), so a claim cut short mid-commit still knows every lease it may hold — a token for a commit that never landed matches no row under the token-fenced release.
- 2026-09-28 — AC8 added and AC7 tightened after the security audit and code review: a cancel followed by the claim failing let the claim's error escape the cancel handler (leases stranded, cancellation lost); and nothing pinned that the release after a claim timeout is token-fenced. A cancelled shield also delays the cancellation by up to the claim budget (`publish_claim_timeout_seconds`) plus driver unwind (bounded by `db_command_timeout_seconds`).
