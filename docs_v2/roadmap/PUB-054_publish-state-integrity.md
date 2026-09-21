# PUB-054: Publish State Integrity — Tenant-Keyed State, Dedup Through the Store, Publishing Lease

| Field | Value |
|-------|-------|
| **ID** | PUB-054 |
| **Category** | Foundation |
| **Priority** | P1 |
| **Effort** | M |
| **Status** | Proposal |
| **Dependencies** | PUB-047 |

## User Story

As a publisher operator, I want a run to either publish something new, or tell me plainly that nothing is left, and never to post the same image twice or block another tenant's image, so that the cron log means what it says.

## Problem

Review [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177), security H1 and performance H3, M1, M10:

1. **Posted state is not tenant-keyed.** `utils/state.py:29-33` stores `posted.json` under `~/.cache` with no tenant argument; `core/workflow.py:129-133` uses it as the dedup veto whenever no publish store exists. Managed storage hashes by ETag (MD5 of bytes). In orchestrated mode without `DATABASE_URL`, tenant A's publish makes tenant B's byte-identical upload return 409 "Image already published", revealing that someone else on the platform published it.
2. **Selection ignores the store.** `_select_image` (`workflow.py:160-161, 208-222`) vetoes only against the file set; the store is consulted afterwards (`:441-456`); already-published platforms are pre-filled as success and the run reports `success=True` with nothing posted (`:962-980`, `:711-716`). With `content.archive=false` or a persistently failing archive, this becomes a permanent "success, nothing published" loop.
3. **Reclaim can double-post.** `db/publish_store.py:353-388` reclaims any `leased` row older than TTL; a SIGKILL between publish and mark, or a swallowed mark failure, leaves the row `leased` and the next run posts the same image again. The TTL floor (`config/runtime_settings.py:170`, 330 s) omits the history fetch, the sidecar HEAD + PUT and the marks.

## Desired Outcome

No tenant can observe or be blocked by another tenant's file-based state. Selection never picks an image the store says is fully published; when nothing remains the run returns a distinct `nothing_left_to_publish` outcome. A crash between publish and mark cannot lead to a second post because a `publishing` status is never reclaimed. The TTL floor covers the whole hold window.

## Scope

**In scope:**
- Per the #181 answer: orchestrated mode refuses to start without `DATABASE_URL`, or the file becomes `{tenant: [...]}` with a one-time migration of the flat list (sub-issue #199)
- Bulk store lookup for the listed hashes folded into selection; `nothing_left_to_publish` outcome with its own exit code and log event (#200)
- `publishing` status set immediately before the publisher gather (additive migration); reclaim only `leased`; `publishing` resolved only by a mark or an operator (#200)
- TTL floor extended with the sidecar and DB claim budgets (#200)
- `CONFIGURATION.md` documents the decision and the outcomes

**Out of scope:**
- Postgres timeouts and fail-closed claim (PUB-047)
- Workflow stage extraction (PUB-058); this item adds the minimum to `_select_image` and the claim and does not restructure

## Acceptance Criteria

- AC1: Given two tenant configs, the same content hash and no store, when tenant B publishes, then tenant B is not vetoed (or, per the decision, the orchestrated app refuses to start without a database and names the variable)
- AC2: Given three images of which two are published on every enabled platform and archive is off, when a run selects, then the third is chosen first time, every time
- AC3: Given every image is fully published and archive is off, when a run executes, then the outcome is `nothing_left_to_publish`, `success` is false, the exit code is distinct from a crash, and no GET beyond the listing was billed
- AC4: Given a row in `publishing` older than the TTL, when the next run claims, then it is not reclaimed; given a row in `leased` older than the TTL, then it is
- AC5: Given a run, when its status transitions are recorded, then they go `leased` → `publishing` → `published` (or `failed`) with the lease token fencing every mark
- AC6: Given `RuntimeSettings`, when the lease TTL floor is computed, then it includes the sidecar and DB claim budgets and a configured TTL below it is raised to it with a warning

## Implementation Notes

- Two sub-issues: #199 (state), #200 (selection, `publishing`, floor).
- The `publishing` value is an additive enum change; migration listed in the PR body per the standing rule.
- Keep the file-state path for standalone mode untouched except for the tenant key.

## Risks

- A `publishing` row left by a genuine crash needs an operator path; add a CLI flag `--release-publishing <hash>` in the same PR and document it.
- Folding a bulk query into selection adds one DB round-trip per run; it replaces the two per-platform queries made later, so net cost falls.

## Success Metrics

- Zero duplicate posts in `publish_record` after deploy.
- Cron logs show `nothing_left_to_publish` on idle days instead of `success`.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issues [#199](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/199), [#200](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/200), [#181](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/181)
- [PUB-006: Core Workflow Dedup Performance](archive/PUB-006_core-workflow-dedup.md)
- Prior fixes #85 (Postgres publish state), #139 (lease expiry)
