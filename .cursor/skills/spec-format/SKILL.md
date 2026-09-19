---
name: spec-format
description: >-
  Documents the PUB-NNN roadmap item file format, its handoff/plan/summary sibling
  files, the status lifecycle, and the exact-pytest-function-name spec-to-test
  traceability rule used across docs_v2/roadmap/. Use when creating, hardening,
  implementing, verifying, or reviewing a roadmap item, or when working with any
  file under docs_v2/roadmap/.
---

# Spec format (flat roadmap)

Every unit of work is one self-contained file: `docs_v2/roadmap/PUB-NNN_slug.md`. No
epics/features/stories hierarchy (see ADR-0002). Shipped items move to
`docs_v2/roadmap/archive/PUB-NNN_slug.md`.

## Sibling files per item

| File | Owner (tool) | Purpose | Lifetime |
|------|--------------|---------|----------|
| `PUB-NNN_slug.md` | Cursor | The spec itself: Problem, Desired Outcome, Scope, Acceptance Criteria | Permanent |
| `PUB-NNN_handoff.md` | Cursor (`/product-harden`) | Implementation contract: test-first targets, mock boundaries, files touched | Deleted after archive |
| `PUB-NNN_plan.yaml` | Claude Code (`/implement`) | Tasks, ACs, quality gates for this implementation pass | Permanent (implementation record) |
| `PUB-NNN_summary.md` | Claude Code (`/implement`) | Files changed, ACs met with test names, test results | Permanent |

## Status lifecycle

`Proposal` → `Not Started` → `In Progress` → `Done` (or `Deferred` / `Superseded`)

Set in the item's header table under `**Status:**`. `/product-harden` sets `Not Started`;
`/product-archive` sets `Done`.

## Required sections in `PUB-NNN_slug.md`

Header table (ID, Category, Priority, Effort, Status, Dependencies), User Story (`As a
<role>, I want <capability>, so that <benefit>` — right after the header table, before
Problem), Problem, Desired Outcome, Scope (in/out), Acceptance Criteria. Implementation
Notes, Risks, Success Metrics, Related are optional but encouraged. See
`.cursor/skills/product-propose-item/SKILL.md` for the exact template and category/priority
vocab.

## The exact-test-name traceability rule

The handoff doc's Test-first targets table has a **Test name (exact function)** column —
the literal `pytest` function name, not a description. This is the *only* mechanical
link between an acceptance criterion and its test. `/implement` must create tests using
that exact name (or record the actual name in the summary doc if it deviates).
`/verify` and `/product-review-delivery` both check the real test function name against
this table; an unexplained mismatch is a traceability gap, not a style nit.

## Full detail

For the exact hardening audit checklist, adversarial-review step, and handoff template,
read `.cursor/skills/product-harden/SKILL.md`. For the implementation workflow, read
`.claude/commands/implement.md` and `.claude/rules/spec-workflow.md`.
