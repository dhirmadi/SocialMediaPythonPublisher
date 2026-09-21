---
name: lease-expiry-review-traps
description: Review traps for publish-lease/TTL work (#139) — leased_at CAS vs server defaults, TTL/timeout coupling, _select_image preview blindness, PublishResponse swallows workflow errors
metadata:
  type: project
---

Traps found reviewing #139 (publish lease expiry) that recur in this repo's DB + workflow + web code.
Items 1-3 were *found and fixed* during #139; keep them as patterns to re-check, not as open bugs.

**1. `PublishRecord.leased_at` compare-and-set does not match server-default rows on SQLite.**
`leased_at` is `DateTime(timezone=True), server_default=func.now()`. Rows created by
`acquire_lease`'s insert branch get SQLite `CURRENT_TIMESTAMP` (second precision, naive UTC), so
`.where(leased_at == existing.leased_at)` renders microseconds and matches **zero rows**. Tests that
"age" a lease with an ORM `update(values(leased_at=datetime.now(UTC)))` write microseconds and pass
anyway. Fix pattern used in #139: compare `leased_at < cutoff`, never `==`.
**How to apply:** for any lease/CAS-on-timestamp change, age the row with raw SQL
(`text("UPDATE pv2_publish_record SET leased_at = datetime('now','-3600 seconds')")`) so the row has
the production shape before trusting the test.

**2. `WorkflowOrchestrator._select_image` knows nothing about `preview_mode` / `dry_publish`.**
Any new veto on the `select_filename` branch also fires for `--select X --preview` and
`--dry-publish` unless the mode is threaded in explicitly (#139 added `respect_posted_state`).
**How to apply:** when reviewing a new early return in `_select_image`, check the CLI preview path.

**3. Lease TTL must be cross-validated against the publish/AI timeouts, not clamped independently.**
`load_runtime_settings` now floors `PUBLISH_LEASE_TTL_SECONDS` at
`ai_stage + max(publish_timeout, *per-platform overrides) + 60`. The floor still excludes image
download, variant rendering and sidecar upload, and `PublishStore.mark()` is unconditional (no
CAS on `leased_at`), so an over-TTL run's success path can still overwrite a reclaimer's row.
**How to apply:** any TTL/timeout tunable pair here needs load-time cross-validation; and any
"fence" added on the abort path should be checked for whether the success path needs the same fence.

**4. A monotonic "how long did I hold the lease" stamp must be taken BEFORE the DB write, not after.**
`lease_claimed_at = now_monotonic()` set *after* `_claim_publish_targets()` makes the in-process age
smaller than the row's real age by the acquire round-trip, so a TTL-based "don't release, it may have
been reclaimed" guard can under-fire. Stamping before the claim makes the guard conservative.

**5. `PublishResponse` (web/models.py) has no `error` field.**
`WebImageService.publish_image` drops `WorkflowResult.error` entirely; the endpoint returns 200 with
`results={}` and `any_success=false`, and index.html renders "no platforms reported success" plus an
empty `{}`. Any new workflow-level early return (e.g. #139's "Already published: <file>") is
therefore invisible to the user unless it is raised as an exception and mapped in
`raise_for_service_error`.
**How to apply:** when a change adds a new `WorkflowResult(success=False, error=...)` return, check
how the web layer surfaces it, and check the test actually asserts the second response, not just
"no side effect happened".
