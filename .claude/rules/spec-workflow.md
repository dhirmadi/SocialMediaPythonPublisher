---
description: "Spec-based TDD implementation workflow for roadmap items"
paths:
  - "docs_v2/roadmap/**"
---

# Spec-based implementation workflow (flat roadmap)

When implementing a roadmap item from a hardened spec:

1. **Read the handoff doc first** (`docs_v2/roadmap/PUB-NNN_handoff.md`). It contains the implementation contract: test targets, mock boundaries, and files to touch.
2. **The spec is the contract.** If implementation and spec disagree, the spec wins.
3. **Test-first, always.** Write failing tests from acceptance criteria before writing any implementation code.
4. **Create plan per roadmap item.** Use `docs_v2/roadmap/PUB-NNN_plan.yaml` with tasks, ACs, and quality gates.
5. **Create summary per roadmap item.** Document files changed, ACs met, test results, and any implementation decisions in `docs_v2/roadmap/PUB-NNN_summary.md`.
6. **Never deviate silently.** If you must deviate from the spec, document why in the summary and flag it for review.
7. **Coverage gates are mandatory.** ≥80% on affected modules, ≥85% overall. Do not skip.

## Roadmap layout

- **Active specs:** `docs_v2/roadmap/PUB-NNN_slug.md`
- **Shipped/archived:** `docs_v2/roadmap/archive/PUB-NNN_slug.md`
- **Handoffs:** `docs_v2/roadmap/PUB-NNN_handoff.md`
- **Plans:** `docs_v2/roadmap/PUB-NNN_plan.yaml`
- **Summaries:** `docs_v2/roadmap/PUB-NNN_summary.md`

Implementation follows the item's acceptance criteria and implementation notes.
