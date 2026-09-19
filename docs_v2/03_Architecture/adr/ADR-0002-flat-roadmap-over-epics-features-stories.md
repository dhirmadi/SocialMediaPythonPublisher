# ADR-0002: Flat roadmap model over Epics/Features/Stories hierarchy

- **Status:** accepted
- **Date:** 2026-09-18 (recorded retroactively — the decision predates this ADR log)
- **Author:** Product Manager Agent (Cursor), documented as part of the AI-tooling config audit
- **Related roadmap item(s):** PUB-000 through PUB-022 (migrated items)

## Context

The original V2 documentation structure organized work as a three-level hierarchy under
`docs_v2/08_Epics/`: Epics → Features → Stories, each in its own nested directory with its own
files. This gave good narrative structure but made it harder to answer simple questions quickly
("what's the status of X", "what's next", "what did Y depend on") without navigating several
directory levels, and it made the Cursor/Claude Code handoff contract less uniform — a "story"
and a "feature" didn't have the same shape.

## Decision

Replace the Epics/Features/Stories hierarchy with a **flat roadmap**: every unit of work is a
single self-contained file, `docs_v2/roadmap/PUB-NNN_slug.md`, with a fixed structure (header
table, Problem, Desired Outcome, Scope, Acceptance Criteria, Implementation Notes). Shipped items
move to `docs_v2/roadmap/archive/PUB-NNN_slug.md`. A single index, `docs_v2/roadmap/README.md`,
lists every item with its category, priority, effort, dependencies, and status.

Items PUB-000 through PUB-022 were migrated from the original hierarchy; the original detailed
story-level documentation is preserved as historical reference under `docs_v2/08_Epics/` (now
itself archived and not edited).

This decision is the foundation ADR-0001's two-tool split builds on: the flat file is exactly
what the handoff doc (`PUB-NNN_handoff.md`), plan (`PUB-NNN_plan.yaml`), and summary
(`PUB-NNN_summary.md`) attach to as siblings — a hierarchy of directories would have made that
sibling-file convention awkward.

## Consequences

- **Positive:** one file per unit of work, one index to scan for roadmap status, uniform shape
  regardless of size (a 1-day fix and a multi-week initiative both get the same header table and
  AC format), and a simple "operates on a single `PUB-NNN_slug.md` file; no feature folders or
  story hierarchy" rule that every `/product-*` skill enforces.
- **Negative / trade-offs:** very large initiatives that genuinely span multiple independent
  deliverables don't get native sub-item tracking — they either become one large item with many
  ACs, or get split into multiple related `PUB-NNN` items linked via the Dependencies column.
  Some sibling repos (e.g. `ldr`) instead use a directory-per-feature model
  (`docs/roadmap/NNN-feature-name/{story,spec,tasks}.md`) that keeps a feature's docs together
  as it grows; that's a reasonable alternative this repo deliberately didn't take.
- **Follow-ups:** none currently open.

## Alternatives considered

- **Keep Epics/Features/Stories** — rejected: too much ceremony for most V2 work, and the
  ownership of "which level does the AC live on" was inconsistent in practice.
- **Directory-per-feature (story.md + spec.md + tasks.md siblings in one folder)** — rejected
  for now: this repo's `PUB-NNN_slug.md` + `PUB-NNN_handoff.md` + `PUB-NNN_plan.yaml` +
  `PUB-NNN_summary.md` sibling-files-in-one-folder convention already gets most of the same
  benefit (everything for one item lives together) without introducing a new directory per item.
