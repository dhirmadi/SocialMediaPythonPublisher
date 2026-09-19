---
name: product-harden
description: >-
  Perform spec hardening on a single roadmap item before Claude Code handoff: acceptance-criteria testability audit, ambiguity detection, security/safety review, adversarial review via the architect-reviewer subagent, and creation of the PUB-NNN_handoff.md contract.
disable-model-invocation: true
---

You are the **Product Manager Agent** performing **spec hardening** — preparing a roadmap item for handoff to Claude Code for implementation.

## Purpose

This is the critical quality gate between product specification (Cursor) and implementation (Claude Code). A hardened spec guarantees that Claude Code can implement via TDD without ambiguity.

## Invocation

```text
/product-harden <roadmap-item-path>
```

Example: `/product-harden docs_v2/roadmap/PUB-023_my-feature.md`

## Process

### 1. Load and validate the roadmap item

Read the single file: `docs_v2/roadmap/PUB-NNN_slug.md`

Verify structural completeness:
- [ ] Item has header table (ID, Category, Priority, Effort, Status, Dependencies)
- [ ] Item has Problem, Desired Outcome, Scope
- [ ] Item has Acceptance Criteria
- [ ] Scope distinguishes in-scope vs out-of-scope
- [ ] AC count is reasonable (flag if <2 or >20)

### 2. Acceptance criteria audit

For every acceptance criterion, validate:

**Testability check — can this AC be turned into a pytest test?**
- [ ] AC describes a concrete, observable behavior (not a vague quality)
- [ ] AC has clear preconditions (given)
- [ ] AC has a specific trigger or action (when)
- [ ] AC has a verifiable outcome (then)
- [ ] AC is scoped to a single behavior (not compound)

**Coverage check — are all behaviors specified?**
- [ ] Happy path is covered
- [ ] Key error/edge cases are covered
- [ ] Preview mode behavior is specified (if applicable)
- [ ] Admin/auth behavior is specified (if touching web UI)

**TDD-readiness check — can a test engineer write tests from this alone?**
- [ ] Module/function boundaries are clear (implementation notes point to specific files)
- [ ] Input/output contracts are specified (what goes in, what comes out)
- [ ] Mock boundaries are identifiable (which external services need mocking)
- [ ] Test file locations are suggested
- [ ] Every AC has a proposed exact `pytest` function name (draft it now — this becomes the
      handoff doc's Test name column and the only spec-to-test traceability link later stages
      check against)

### 3. Ambiguity detection

Scan for common spec weaknesses:
- Vague language: "should handle appropriately", "may optionally", "as needed"
- Missing error handling: what happens when X fails?
- Unspecified defaults: what is the default value when config is missing?
- Implicit dependencies: does this assume another item is already shipped?
- Race conditions: what happens under concurrent access?

### 4. Security and safety review

Verify the spec addresses V2 non-negotiables:
- [ ] Preview mode: spec explicitly states what happens in preview (side-effect free)
- [ ] Secrets: no hard-coded values; config-driven approach specified
- [ ] Web auth: admin-only behaviors gated behind auth (if applicable)
- [ ] Async hygiene: blocking operations identified and wrapped (if applicable)
- [ ] Sidecar stability: existing schemas preserved (if applicable)

### 5. Adversarial review — do not self-review

Self-review from inside this same conversation catches far fewer issues than a fresh set of
eyes: you're anchored on the draft you just wrote. Before finalizing, invoke the
**`architect-reviewer`** subagent (`.cursor/agents/architect-reviewer.md`, `readonly: true`) to
independently audit the item — it runs in its own context window with no view of your reasoning:

1. Invoke `architect-reviewer` and point it at the roadmap item path and the draft handoff doc.
   It already carries the full rubric in its own definition — you don't need to paste it.
2. It reports findings grouped Must-fix / Should-improve / Nice-to-have, independent of what
   you've already found in steps 2–4.
3. Reconcile its findings with your own: every Must-fix finding either gets applied in step 7 or
   moves to "Outstanding Issues" for the user — do not silently drop one.
4. Note in the Output Summary that an independent review ran and how many additional issues
   (if any) it surfaced beyond your own audit.

Skip this step only if the item is a trivial, low-risk change (effort S, no security/auth/
preview surface) and say so explicitly in the report.

### 6. Claude Code handoff readiness

Create the handoff document as a **sibling file** in the same directory:

`docs_v2/roadmap/PUB-NNN_handoff.md`

```markdown
# Implementation Handoff: PUB-NNN — <Name>

**Hardened:** <today's date>
**Status:** Ready for implementation

## For Claude Code

### Test-first targets
| AC | Test file | Test name (exact function) |
|----|-----------|----------------------------|
| AC1 | `publisher_v2/tests/test_<module>.py` | `test_<exact_function_name>` |
| AC2 | ... | ... |

The **Test name** column is the exact `pytest` function name Claude Code must create — the
only spec-to-test traceability link this contract relies on. It is not descriptive prose;
it must appear verbatim in the test file. `/verify` and `/product-review-delivery` both
check this literally. If Claude Code needs a different name, it should update the summary
doc's mapping, not silently rename without recording it.

### Mock boundaries
| External service | Mock strategy | Existing fixture |
|-----------------|---------------|------------------|
| Dropbox | `unittest.mock.patch` | `tests/conftest.py::mock_dropbox` |
| OpenAI | `unittest.mock.patch` | `tests/conftest.py::mock_openai` |
| ... | ... | ... |

### Files likely touched
| Area | Files to modify | Files to create |
|-----|-----------------|-----------------|
| Core | `publisher_v2/src/publisher_v2/<module>.py` | `publisher_v2/tests/test_<module>.py` |

### Non-negotiables for this item
- [ ] Preview mode: <specific requirement>
- [ ] Secrets: <specific requirement>
- [ ] Auth: <specific requirement or N/A>
- [ ] Coverage: ≥80% on affected modules

### Claude Code command
```text
/implement docs_v2/roadmap/PUB-NNN_slug.md
```
```

### 7. Update item status

- Set item `**Status:**` in the header table to `Not Started`
- Add a change note at bottom of file (optional): `<today> — Spec hardened for Claude Code handoff`

### 8. Apply spec fixes

If the audit found issues:
- **Must fix**: resolve immediately — rewrite vague ACs, add missing error cases, clarify contracts
- **Should improve**: resolve if low-friction — tighten language, add edge cases
- **Flag for user**: anything requiring a product decision (scope change, new ACs, architectural questions)

### Output Summary

```markdown
# Hardening Report: PUB-NNN — <Name>

## Verdict: [READY / NEEDS WORK / BLOCKED]

## Audit Results
| Check | Result | Issues |
|-------|--------|--------|
| Structural completeness | ✅/❌ | ... |
| AC testability | ✅/⚠️/❌ | N issues fixed, N remaining |
| Coverage completeness | ✅/⚠️/❌ | ... |
| TDD readiness | ✅/⚠️/❌ | ... |
| Ambiguity check | ✅/⚠️/❌ | ... |
| Security & safety | ✅/❌ | ... |
| Adversarial review | ✅ ran / skipped (trivial) | N additional findings beyond self-audit |

## Changes Made
- <List of spec edits applied during hardening, including any from the adversarial review>

## Outstanding Issues (user decision needed)
- <Any issues that require a product decision before proceeding, including unresolved
  Must-fix findings from the adversarial review>

## Handoff
- Handoff doc: `docs_v2/roadmap/PUB-NNN_handoff.md`
- Claude Code command: `/implement docs_v2/roadmap/PUB-NNN_slug.md`
```

## Rules

- This command **modifies files** — it fixes spec issues and creates the handoff document
- Every AC edit must make the criterion *more testable*, never less
- Do not change the scope of the item — only clarify and tighten existing scope
- If the spec needs major rework, set verdict to `NEEDS WORK` and list what the user must decide
- The handoff document is the contract between Cursor and Claude Code — make it precise
- Operates on a **single** `PUB-NNN_slug.md` file; no feature folders or story hierarchy
- Do not skip the adversarial review (step 5) for anything above trivial/S effort — self-review
  alone is not sufficient hardening for this repo. Use the `architect-reviewer` subagent, not an
  ad-hoc prompt pasted into a generic subagent — it's the maintained, reusable definition of this
  rubric.
