---
name: product-archive
description: >-
  Close out a delivered roadmap item: move it to docs_v2/roadmap/archive/, record the Verified evidence line (PR#/commit/tests/coverage), update the roadmap README and CHANGELOG, and delete the transient handoff doc. Requires a passed product-review-delivery.
disable-model-invocation: true
---

You are the **Product Manager Agent** performing **roadmap item completion and archival** — the final stage of the lifecycle.

## Purpose

Close out a delivered roadmap item: move it to archive, update status, update the index, update CHANGELOG, and clean up handoff artifacts.

## Invocation

```text
/product-archive <roadmap-item-path>
```

Example: `/product-archive docs_v2/roadmap/PUB-023_my-feature.md`

## Prerequisites

- Item must have passed `/product-review-delivery` (verdict: APPROVED)
- All quality gates must be green
- Item should be deployed (or ready to deploy)
- Have the PR number and merge commit SHA on hand (from GitHub, or from
  `git log --oneline -1 <branch>`) — needed for the evidence trail in step 3

## Process

### 1. Verify readiness

- [ ] Item `PUB-NNN_slug.md` exists in `docs_v2/roadmap/` with acceptance criteria
- [ ] Review record exists (from `/product-review-delivery`)
- [ ] Tests pass: run `uv run pytest -v --tb=short` to confirm

If any prerequisite is missing, stop and report what's needed.

### 2. Move item to archive

- Move `docs_v2/roadmap/PUB-NNN_slug.md` → `docs_v2/roadmap/archive/PUB-NNN_slug.md`
- Do **not** move `PUB-NNN_handoff.md` — it is cleaned up (see step 6)

### 3. Update item status

In the archived file (`docs_v2/roadmap/archive/PUB-NNN_slug.md`):
- Set `**Status:**` in the header table to `Done`
- Add `**Shipped date:**` with today's date
- Add a **Verified** line directly under the header table capturing the evidence trail, so
  the archived item is self-contained proof it was actually delivered (not just a status
  word) — this is what closes gaps like the PUB-046 drift found in the 2026-09 config audit.
  Pull the numbers from `/product-review-delivery`'s Quality Gates table and the PR:

  ```markdown
  **Shipped date:** YYYY-MM-DD
  **Verified:** PR #<n>, merge commit `<short-sha>`; <N> passed / <M> skipped, coverage <P>%
  overall; ruff check + ruff format --check clean; mypy clean.
  ```

  If any of these facts aren't available (e.g. no PR was opened, or coverage wasn't run),
  say so explicitly rather than omitting the line — an honest "PR not tracked" beats silence.
- Add checkmarks (✅) to verified acceptance criteria

### 4. Update roadmap index

In `docs_v2/roadmap/README.md`:
- Update the item's row: change the link from `PUB-NNN_slug.md` to `archive/PUB-NNN_slug.md`
- Set the Status column to `Done`
- Ensure the item appears in the appropriate shipped section (grouped by category or theme)

### 5. Update CHANGELOG.md

Add the item to `CHANGELOG.md` under `[Unreleased]` (or create the section if it doesn't exist):

```markdown
### Added - PUB-NNN: <Name>
- <One-line summary of key capability 1>
- <One-line summary of key capability 2>
- ...
```

Follow the existing CHANGELOG format and conventions (see current entries for style).

### 6. Clean up handoff doc

- Delete `docs_v2/roadmap/PUB-NNN_handoff.md` (no longer needed; implementation is complete)
- If the handoff doc was moved to archive by mistake, delete it from archive as well — handoff docs are transient implementation contracts

### 7. Output summary

```markdown
# Archival Complete: PUB-NNN — <Name>

## Summary
- **Item:** PUB-NNN — <Name>
- **Shipped:** <date>
- **Verified:** PR #<n>, commit `<sha>`; <test counts>; coverage <P>%
- **Location:** `docs_v2/roadmap/archive/PUB-NNN_slug.md`

## Updated Artifacts
| Artifact | Action |
|----------|--------|
| `PUB-NNN_slug.md` | Moved to archive, Status → Done |
| `docs_v2/roadmap/README.md` | Index updated |
| `CHANGELOG.md` | Entry added |
| `PUB-NNN_handoff.md` | Deleted |

## CHANGELOG Entry
<The generated CHANGELOG entry>

## Roadmap Impact
- <Brief note on what's unblocked, what's next>
```

## Rules

- Only archive items that have passed review — never skip the review gate
- The item file is **moved** to `archive/`, not copied — it no longer lives in the active roadmap folder
- CHANGELOG entries must follow the existing format in `CHANGELOG.md`
- Delete the handoff doc — it is an implementation artifact, not permanent documentation
- Operates on a **single** `PUB-NNN_slug.md` file; no feature folders or story hierarchy
- Every archived item gets a **Verified** evidence line (PR #, commit SHA, test/coverage
  numbers) — don't archive with just a bare "Done" status word and nothing to check it against
