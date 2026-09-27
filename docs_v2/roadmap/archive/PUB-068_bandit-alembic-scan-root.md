# PUB-068: Add `publisher_v2/alembic` to the Bandit Scan Roots

| Field | Value |
|-------|-------|
| **ID** | PUB-068 |
| **Category** | Ops |
| **Priority** | P3 |
| **Effort** | XS |
| **Status** | Superseded |
| **Dependencies** | PUB-055 (merged, #236) |
| **Archived date** | 2026-09-27 |

> **Superseded 2026-09-27.** Merged into [PUB-078: CI Security-Gate Cleanup Batch](../PUB-078_ci-security-gate-cleanup-batch.md)
> along with PUB-067 and PUB-069 — all three are small, independent fixes to the same PUB-055 tooling,
> batched to reduce the number of separately-tracked security roadmap items. No scope changed; see
> PUB-078 for the current AC set (AC3-AC4 there trace to this item's AC1-AC2).

## Problem

`.pre-commit-config.yaml` runs bandit with `-r publisher_v2/src scripts`. PUB-055 deleted
`security-scan.yml`'s `bandit -r . || true` step, which nominally walked the whole repository.

Nothing that was *enforced* became unenforced — the deleted step was `|| true` and could never fail
a build, so bandit's real enforcement went from zero to genuine when #229 added the `pre-commit`
job. But there is a literal scan-root gap: `publisher_v2/alembic/env.py` and
`publisher_v2/alembic/versions/00{1,2,3}_*.py` are four shipped, non-archived source files that no
bandit invocation now covers.

## Desired Outcome

Bandit's roots cover the shipped source tree, with no unexplained omission.

## Scope

**In scope:** adding `publisher_v2/alembic` to the bandit hook's args; triaging whatever it reports
(migrations are low-risk for bandit's rule set, but the finding count is unknown until run).

**Out of scope:** `publisher_v2/tests/**` (B101 assert noise by nature) and `code_v1/**` (archived,
never edited).

## Acceptance Criteria

- AC1: `uv run pre-commit run bandit --all-files` covers `publisher_v2/alembic` and passes.
- AC2: Any finding is either fixed or carries a justified `# nosec` with a reason, matching the
  existing convention in `config/orchestrator_client.py`, `web/service.py` and `services/ai.py`.

## Related

- Parent tracker [#243](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/243) · PUB-055 (#236) · #229
