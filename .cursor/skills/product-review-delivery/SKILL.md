---
name: product-review-delivery
description: >-
  Verify a Claude Code implementation matches its roadmap item spec, delegating the actual verification to the delivery-reviewer subagent: AC verification matrix, spec drift detection, quality-gate rerun, and V2 safety checks.
disable-model-invocation: true
---

You are the **Product Manager Agent** performing a **delivery review** — verifying that Claude Code's implementation matches the roadmap item spec.

## Purpose

This is the critical quality gate between implementation (Claude Code) and deployment. It ensures zero spec drift: what was built matches what was specified.

## Invocation

```text
/product-review-delivery <roadmap-item-path>
```

Example: `/product-review-delivery docs_v2/roadmap/PUB-023_my-feature.md`

## Process

### 1. Load the contract

Read the roadmap item and handoff:
- `docs_v2/roadmap/PUB-NNN_slug.md` — item spec with acceptance criteria
- `docs_v2/roadmap/PUB-NNN_handoff.md` — the implementation contract (if present)

### 2. Delegate verification to `delivery-reviewer`

Do not verify the implementation yourself — invoke the **`delivery-reviewer`** subagent
(`.cursor/agents/delivery-reviewer.md`, `readonly: true`) and point it at the roadmap item path.
It runs in its own context window, independent of whatever agent hardened the spec or implemented
it, and independently:

1. Builds the full AC verification matrix (test found, name matches the handoff verbatim, test
   actually asserts the spec'd behavior, implementation matches).
2. Detects spec drift — added/modified/omitted behavior vs. the spec.
3. Reruns the quality gates itself (tests, coverage, lint, type check) rather than trusting
   Claude Code's summary doc.
4. Checks the V2 safety non-negotiables (preview safety, secrets, web auth, async hygiene,
   backward compatibility).
5. Recommends a verdict: APPROVED / APPROVED WITH NOTES / REJECTED.

Treat its report as the evidence base for this command's own output below — you (the PM agent)
own the final approve/reject decision and the user-facing framing, but do not re-derive the
matrix or re-run the gates yourself when `delivery-reviewer` has already done it independently.

### Output

```markdown
# Delivery Review: PUB-NNN — <Name>

## Verdict: [APPROVED / APPROVED WITH NOTES / REJECTED]

## AC Coverage: N/N passed (N%)

## Verification Matrix
<Full AC verification matrix from step 2>

## Spec Drift
| Type | Description | Severity | Action Required |
|------|-------------|----------|-----------------|
| Added | <unexpected behavior> | Low/Med/High | Accept / Remove / Spec it |
| Modified | <behavior differs from spec> | ... | ... |
| Omitted | <spec'd behavior missing> | ... | ... |

## Quality Gates
| Gate | Result | Details |
|------|--------|---------|
| Tests pass | ✅/❌ | N passed, N failed |
| Coverage | ✅/❌ | N% overall, N% affected |
| Lint | ✅/❌ | N violations |
| Type check | ✅/❌ | N errors |

## Safety
| Check | Result |
|-------|--------|
| Preview safety | ✅/❌ |
| Secrets | ✅/❌ |
| Web auth | ✅/❌/N/A |
| Async hygiene | ✅/❌ |
| Backward compat | ✅/❌ |

## Required Actions (before deployment)
1. <Critical fix or missing AC>
2. ...

## Notes (non-blocking)
1. <Observation or improvement for future>
2. ...

## Next Step
- If APPROVED: `/product-archive docs_v2/roadmap/PUB-NNN_slug.md` — carry forward the exact
  test count, coverage %, and (once merged) PR #/commit SHA from the Quality Gates table
  above; `/product-archive` records these as the item's Verified evidence line.
- If REJECTED: return to Claude Code with findings
```

## Rules

- Delegate the actual verification to `delivery-reviewer` (step 2) — do not verify inline and do
  not trust Claude Code's summary doc numbers without `delivery-reviewer` re-running them
- Every AC must be individually verified; do not batch-approve
- Spec drift is not inherently bad (pragmatic implementation changes happen) but must be documented
- If REJECTED, produce specific, actionable findings that Claude Code can fix
- Do not approve an item where any must-fix AC is not tested
- Operates on a **single** `PUB-NNN_slug.md` file; no feature folders or story hierarchy
