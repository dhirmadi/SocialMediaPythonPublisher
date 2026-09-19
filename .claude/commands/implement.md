---
description: Spec-based TDD implementation of a roadmap item from hardened spec
allowed-tools: Bash, Read, Write, Edit, Agent
---

# Implement Roadmap Item (Spec-Based TDD)

You are the **Lead** implementing a roadmap item that has been specified, reviewed, and hardened
in Cursor. The spec is your contract. You do not write tests or implementation code yourself —
you read the contract, delegate each TDD phase to the matching subagent in `.claude/agents/`, and
reconcile their reports. This is the real, always-available version of the "teams mode" roles
described in `CLAUDE.md` (Lead/Test engineer/Developer/Reviewer): it works via the `Agent` tool in
a normal session, without needing `CLAUDE_CODE_TEAMMATE_MODE=tmux`.

## Input

The user provides a roadmap item path: `$ARGUMENTS`

Example: `docs_v2/roadmap/PUB-023_something.md`

If no path is provided, ask for the roadmap item path under `docs_v2/roadmap/`.

## Workflow

### Step 1: Read the Contract

1. Read the roadmap item spec: `docs_v2/roadmap/PUB-NNN_slug.md`
   - Extract: goals, non-goals, acceptance criteria, implementation notes
2. Read the handoff document: `docs_v2/roadmap/PUB-NNN_handoff.md`
   - Contains: implementation order, test-first targets, mock boundaries, files to touch

If the handoff doc doesn't exist, read the roadmap item spec directly and plan from it.

**Stop and report** if:
- The roadmap item path doesn't exist
- There's no spec doc
- Acceptance criteria are vague or untestable (ask the user to run `/product-harden` in Cursor first)

### Step 2: Create Implementation Plan

Create an implementation plan (inline or as `docs_v2/roadmap/PUB-NNN_plan.yaml`):

- `version`, `roadmap_id` (PUB-NNN), `summary`
- `repo_constraints` (allowed/excluded paths)
- `acceptance_criteria` (from the spec)
- `tasks` (ordered, with file paths)
- `quality_gates` (coverage minimums, safety checks)

Keep the plan minimal — only what's needed to satisfy the ACs.

### Step 3: Delegate the Red Phase to `test-engineer`

Invoke the `test-engineer` subagent (`Agent` tool, `agent_type: test-engineer`) with: the roadmap
item path, the handoff doc's Test-first targets table, and the implementation plan from Step 2.
Do not write tests yourself — that agent's isolation from the implementation is the point.

Wait for its report: test files created, test names (must match the handoff's exact function
names), and confirmation each test fails for the right reason. If it flags spec ambiguity, resolve
it yourself against the roadmap item before moving on — don't pass an unresolved ambiguity
downstream.

### Step 4: Delegate the Green Phase to `developer`

Invoke the `developer` subagent (`Agent` tool, `agent_type: developer`) with: the roadmap item
path, the handoff doc, and the exact failing test names from Step 3. Do not write implementation
code yourself.

Wait for its report: files changed under `publisher_v2/src/`, confirmation the target tests now
pass, and confirmation the full suite still passes. If it reports a concern that an existing test
looks wrong, do not let it fix the test — resolve that yourself against the spec (fix the code if
the test is right; fix the test only if the test is genuinely wrong per the spec).

If `developer`'s report shows a failing or partially-green suite, send it back with the specific
failure instead of proceeding to review.

### Step 5: Delegate Review to `code-reviewer` (and `security-auditor` if applicable)

Invoke the `code-reviewer` subagent (`Agent` tool, `agent_type: code-reviewer`) with the roadmap
item path. It re-runs the full quality gate suite itself and checks spec-to-test traceability,
test integrity, and the non-negotiables — treat its report as authoritative, not a formality.

If the change touches `publisher_v2/web/**`, auth, secrets, or credential/config loading (or the
roadmap item is flagged security-sensitive), also invoke `security-auditor` (`agent_type:
security-auditor`) and fold its verdict into this step.

If either subagent reports a **BLOCKED** verdict, route the specific finding back to `developer`
(or `test-engineer`, if the finding is about test integrity) and re-run Steps 4–5 until both come
back clean. Do not downgrade a blocker to proceed anyway, and do not fix a reviewer's blocker
yourself in this Lead role — send it back to the agent whose job it is, so the fix stays inside
the same TDD role separation.

Record the final verdicts (including coverage numbers) — you'll need them for the summary and for
`/product-review-delivery`'s evidence trail.

### Step 6: Create Summary

Create `docs_v2/roadmap/PUB-NNN_summary.md`:

```markdown
# PUB-NNN — <Name>: Implementation Summary

**Status:** Implementation Complete
**Date:** <today>

## Files Changed
- `publisher_v2/src/publisher_v2/<file>` — <what changed>
- `publisher_v2/tests/test_<file>.py` — <tests added>

## Acceptance Criteria
- [x] AC1 — <description> (test: `test_<name>`)
- [x] AC2 — ...

## Test Results
<paste test output summary>

## Quality Gates
- Format: ✅
- Lint: ✅
- Type check: ✅
- Tests: N passed, 0 failed
- Coverage: N% overall

## Subagent Verdicts
- `code-reviewer`: PASS / PASS WITH NITS / BLOCKED (resolved) — <one line>
- `security-auditor`: PASS / N/A (not security-sensitive) — <one line>

## Notes
<any implementation decisions or deviations from spec>
```

## Non-Negotiables

- **Preview safety:** Preview mode must never publish, archive, or mutate state.
- **No secrets:** Never hard-code tokens, passwords, or API keys.
- **Async hygiene:** No blocking calls in async paths without `asyncio.to_thread()`.
- **Web auth:** Mutating endpoints require auth per `publisher_v2.web.auth`.
- **Backward compatibility:** Do not break CLI flags, endpoint contracts, or config semantics.

## Critical Rules

- **The spec is the contract.** If something is ambiguous, read the spec again. If still ambiguous, ask the user.
- **Tests before code.** Always. No exceptions.
- **Never adjust tests to match incorrect code.** If a test fails, determine whether the test or the code is wrong by checking the spec.
- **Minimal implementation.** Write the simplest code that satisfies the ACs. No speculative features.
- **Role separation is structural, not advisory.** As Lead, you plan and reconcile; you don't
  write the tests (`test-engineer`'s job) or the implementation (`developer`'s job) yourself, and
  you don't self-review (`code-reviewer`'s / `security-auditor`'s job). If a subagent call fails or
  isn't available in your current environment, say so explicitly and fall back to doing that
  phase yourself inline — don't silently skip Steps 3–5.
