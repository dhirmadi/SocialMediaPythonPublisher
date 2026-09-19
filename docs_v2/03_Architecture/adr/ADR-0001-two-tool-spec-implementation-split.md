# ADR-0001: Two-tool spec/implementation split (Cursor + Claude Code)

- **Status:** accepted
- **Date:** 2026-09-18 (recorded retroactively — the decision predates this ADR log)
- **Author:** Product Manager Agent (Cursor), documented as part of the AI-tooling config audit
- **Related roadmap item(s):** none (process decision, not a product item)

## Context

This repo previously had a parallel implementation path: a `roles/` + `feature/00_implementitem`
system where Cursor itself (via a "SW" role) wrote specs *and* implementation code directly.
At the same time, `CLAUDE.md`/`AGENTS.md` documented a competing model where Claude Code owns
implementation via `/implement` + `/verify`. The two systems duplicated responsibility and gave
contributors (human and AI) no single answer to "which tool implements this feature."

## Decision

Cursor and Claude Code have distinct, non-overlapping responsibilities in the roadmap-item
lifecycle:

- **Cursor** owns product management: CREATE (`/product-propose-item`), HARDEN
  (`/product-harden`), REVIEW (`/product-review-delivery`), DEPLOY (`/product-deploy`), ARCHIVE
  (`/product-archive`). Cursor never writes implementation code in `publisher_v2/**`.
- **Claude Code** owns implementation: IMPLEMENT (`/implement`), VERIFY (`/verify`). Claude Code
  never authors or approves the roadmap spec itself.
- The **roadmap item + handoff doc** (`docs_v2/roadmap/PUB-NNN_slug.md` +
  `docs_v2/roadmap/PUB-NNN_handoff.md`) is the contract that bridges the two tools.

The older `roles/` + `feature/` + `stories/` system was archived to
`.cursor/commands/_archived/` (READMEs there explain the retirement) rather than deleted, so the
history is preserved but the system is not resurrected without an explicit instruction.

## Consequences

- **Positive:** one authoritative lifecycle (see ADR-0002's sibling roadmap-model decision and
  `/product-lifecycle`), no ambiguity about which tool does what, and a clean isolation boundary
  — Cursor's Product Manager Agent literally lists "Implement code changes in `publisher_v2/**`"
  under "What You Do NOT Do" in `.cursor/commands/product/_agent.md`.
- **Negative / trade-offs:** every feature pays a two-tool round-trip cost (hardening in Cursor,
  then a context switch to Claude Code, then a review round-trip back to Cursor). Simple,
  low-risk changes still go through the full handoff unless explicitly fast-tracked.
- **Follow-ups:** none currently open. If a future need arises for Cursor to implement small,
  low-risk fixes directly (bypassing the handoff), that would itself need a new ADR superseding
  this one — not a quiet exception.

## Alternatives considered

- **Single-tool (Cursor does everything, including implementation)** — rejected: this is what
  the archived `roles/`/`feature/` system did, and it duplicated/contradicted the Claude Code
  side without a clear reason to run both. Also loses the benefit of a second, independent set
  of eyes (a different tool/context) reviewing the delivered code against the spec.
- **Single-tool (Claude Code does everything, including product management)** — rejected: this
  is the pattern used by some sibling repos (e.g. `tatiimmobot`, `ldr`), and it works, but this
  repo already had a more granular 7-stage lifecycle (HARDEN and REVIEW as distinct gates) that
  benefits from Cursor's longer-lived project/roadmap context living outside the implementation
  loop.
