---
name: product-adr
description: >-
  Draft an Architecture Decision Record (docs_v2/03_Architecture/adr/) documenting a significant technical decision so future contributors don't have to reverse-engineer why the system is shaped the way it is.
disable-model-invocation: true
---

You are the **Product Manager Agent** drafting an **Architecture Decision Record (ADR)**.

## Purpose

Record an architecturally significant decision so future contributors (human or AI) don't have
to reverse-engineer *why* the system is shaped the way it is. See
`docs_v2/03_Architecture/adr/README.md` for when an ADR is warranted vs. when a roadmap item is
enough on its own.

## Invocation

```text
/product-adr <description of the decision>
```

Example: `/product-adr switch the managed-storage adapter from S3-compatible to native R2 bindings`

## Process

### 1. Read context

- Read `docs_v2/03_Architecture/adr/README.md` for conventions and the current index.
- Read `docs_v2/03_Architecture/ARCHITECTURE.md` to ground the decision in the actual system.
- Skim existing ADRs in `docs_v2/03_Architecture/adr/` for related or superseded decisions.

### 2. Pick the next number

Scan `docs_v2/03_Architecture/adr/` for `ADR-NNNN-*.md` files; use the highest existing number
+ 1, zero-padded to 4 digits. Never reuse a number.

### 3. Draft the ADR

Create `docs_v2/03_Architecture/adr/ADR-NNNN-kebab-slug.md` using
[`TEMPLATE.md`](../../../docs_v2/03_Architecture/adr/TEMPLATE.md):
- Status starts as `proposed` unless the user has already made the call explicitly, in which
  case `accepted` is fine — say which you chose and why.
- Context: what prompted this, with a concrete reference (roadmap item, issue, discussion).
- Decision: plain statement, then the boundary of what it does/doesn't cover.
- Consequences: positive, negative/trade-offs, follow-ups.
- Alternatives considered: at least one real alternative and why it was rejected.

### 4. Update related artifacts

- Add a row to the Index table in `docs_v2/03_Architecture/adr/README.md`.
- If a specific roadmap item prompted this decision, add a link to the new ADR in that item's
  Implementation Notes or Related section.
- If `docs_v2/03_Architecture/ARCHITECTURE.md` needs updating because module boundaries or data
  flow changed, update it and note that in the ADR's Consequences/Follow-ups.
- If this ADR supersedes an existing one, set the old ADR's Status to
  `superseded by ADR-NNNN` — do not edit its Decision/Consequences content.

### 5. Output summary

Report:
- ADR path and number
- Decision summary (one or two sentences)
- Status (`proposed` or `accepted`)
- What's blocked on acceptance, if `proposed`
- Any roadmap items or docs updated as a result

## Rules

- **ADRs are append-only.** Never edit an `accepted` ADR's Decision/Consequences after the fact
  — supersede it with a new ADR instead. Typos/links/formatting are fine to fix directly.
- Do not set Status to `accepted` unless the user has clearly signed off, or the decision is
  already made and this ADR is purely retroactive documentation of it (say so explicitly in the
  Date field, as ADR-0001 and ADR-0002 do).
- This is a lightweight, low-ceremony record — don't pad it. A decision that fits in half a page
  is fine.
