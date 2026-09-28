# Implementation Handoff: PUB-086 — Release Leases Claimed Before a Cancellation

**Status:** Ready for implementation

## For Claude Code

One PR from branch `fix/pub-086-release-leases-on-cancel`.

### Test-first targets

| AC | Test name (exact function) | File |
|----|----------------------------|------|
| AC1 | `test_cancel_right_after_a_lease_commit_releases_it` | `test_workflow_partial_publish.py` |
| AC2 | `test_cancel_mid_claim_releases_every_committed_lease` | `test_workflow_partial_publish.py` |
| AC3 | `test_cancel_during_claim_still_raises_cancelled` | `test_workflow_partial_publish.py` |
| AC6 | `test_second_cancel_during_claim_still_releases_committed_leases` | `test_workflow_partial_publish.py` |
| AC7 | `test_claim_timeout_after_a_commit_releases_it` | `test_workflow_partial_publish.py` |
| AC8 | `test_cancel_then_claim_timeout_releases_and_raises_cancelled` | `test_workflow_partial_publish.py` |

### Mock boundaries

The real `PublishStore` on a file-backed SQLite DB; publishers and AI are test doubles, as in the existing tests in that file. The deterministic cancel point is an `asyncio.Event` set after the real `AsyncSession.commit`.

### Non-negotiables

- No fixed sleeps; every wait has a timeout.
- The existing lease, fencing and cancellation tests pass unchanged.
- `code-reviewer` and `security-auditor` (async hygiene: shield/cancel handling).

### Claude Code command

```
/implement PUB-086
```
