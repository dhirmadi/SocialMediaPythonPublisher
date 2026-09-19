# Architecture Decision Records (ADRs)

A lightweight, append-only log of architecturally significant decisions for the Social Media
Python Publisher V2 — things that are expensive to reverse or that future contributors (human
or AI) will otherwise have to reverse-engineer from git history.

## When to write one

Write an ADR when a change:
- Adds, removes, or replaces a module boundary, external dependency, or datastore
- Changes an existing contract (CLI flag, endpoint, config semantic) in a backward-incompatible
  way, with explicit sign-off to do so
- Picks between two or more genuinely reasonable approaches and the reasoning isn't obvious from
  the code alone
- Reverses or supersedes a previous ADR

Do **not** write an ADR for routine feature work that fits cleanly within existing boundaries —
that's what roadmap items in `docs_v2/roadmap/` are for. An ADR records *why the shape of the
system is what it is*; a roadmap item records *what was built*.

## Numbering and lifecycle

- Files are named `ADR-NNNN-kebab-slug.md`, zero-padded to 4 digits, numbered sequentially.
- Status is one of: `proposed`, `accepted`, `superseded by ADR-NNNN`.
- **ADRs are append-only.** Never edit an `accepted` ADR's Decision/Consequences content after
  the fact — if the decision changes, write a new ADR that supersedes it, and mark the old one
  `superseded by ADR-NNNN`.
- Typos, broken links, and formatting fixes are fine to edit directly.

## Who writes them

- `/product-adr` (Cursor) drafts a new ADR from a described decision.
- Any roadmap item, handoff doc, or hardening report that makes an architecturally significant
  call should link to the relevant ADR (existing or newly drafted) rather than re-explaining the
  reasoning inline.
- `/product-harden`'s adversarial-review step (the `architect-reviewer` subagent, see
  `.cursor/agents/architect-reviewer.md`) is a good moment to notice "this should have been an
  ADR" and flag it.

## Template

See [`TEMPLATE.md`](TEMPLATE.md).

## Index

| ADR | Title | Status |
|-----|-------|--------|
| [ADR-0001](ADR-0001-two-tool-spec-implementation-split.md) | Two-tool spec/implementation split (Cursor + Claude Code) | accepted |
| [ADR-0002](ADR-0002-flat-roadmap-over-epics-features-stories.md) | Flat roadmap model over Epics/Features/Stories hierarchy | accepted |
