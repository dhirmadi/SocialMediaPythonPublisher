# PUB-074: Require Mutation Proof for Regression-Guard Tests in Review

| Field | Value |
|-------|-------|
| **ID** | PUB-074 |
| **Category** | Foundation |
| **Priority** | P1 |
| **Effort** | XS |
| **Status** | Superseded |
| **Dependencies** | — |
| **Archived date** | 2026-09-27 |

> **Superseded 2026-09-27.** Folded into [PUB-079: Dependabot Correctness and Scope Batch](../PUB-079_dependabot-correctness-and-scope-batch.md)
> as a prep step — its two doc-edit deliverables (`.claude/agents/code-reviewer.md` and
> `.claude/rules/testing.md`) are now a prerequisite of PUB-079's guard-test work rather than a
> standalone roadmap item. No scope changed.

## User Story

As a maintainer, I want the review role to prove a regression-guard test fails when its defect is
reintroduced, so that a test written to stop a bug recurring is never accepted on the strength of
reading it.

## Problem

A test whose purpose is "this defect cannot come back" is uniquely easy to make vacuously green, and
uniquely useless when it is: it reports safety forever while asserting nothing. Reading such a test
does not reveal the failure — running it against the reintroduced defect does.

This is not hypothetical in this repository:

- **PUB-066.** `test_no_requirements_file_references_a_missing_target` enumerated tracked files with
  the git pathspec `*requirements*.txt` but filtered basenames against `requirements*.txt`. A
  `dev-requirements.txt` holding a dangling `-r` was therefore fetched and then silently skipped —
  the precise defect the guard existed to prevent, passing green. The first `code-reviewer` pass
  returned PASS on it. A second pass found it within minutes by staging such a file.
- The same review also found that AC2's matcher toggled a single boolean on every ``` fence, so one
  unbalanced fence silently inverted the scanned region for the rest of a file: a guard that got
  weaker as the docs grew, invisibly.
- `.claude/agent-memory/code-reviewer/mutation-check-review-technique.md` already records this
  technique, which is evidence the lesson keeps being re-derived per-session rather than required by
  the role's own instructions.

Today whether this check happens depends on the Lead thinking to ask for it by name in the review
prompt. That is not a process.

## Desired Outcome

`code-reviewer` mutation-checks every regression-guard test in a diff as a matter of course, and says
in its report what it reintroduced and what the test then printed — or states explicitly that it
could not, and why.

## Scope

**In scope:**
- `.claude/agents/code-reviewer.md` — add mutation proof as a required step for any test the diff
  presents as preventing recurrence, and require the report to name the mutation and quote the
  resulting failure.
- `.claude/rules/testing.md` — state the rule where test authors will read it: a guard test is not
  done until it has been observed failing.
- Define "regression-guard test" concretely enough to be actionable: a test that asserts the *absence*
  of a condition across a directory, repo or config, rather than the behaviour of one function.
- A short worked example, citing PUB-066's pathspec/basename mismatch.

**Out of scope:**
- A mutation-testing tool or dependency (`mutmut`, `cosmic-ray`). This is a review-discipline change,
  not a new CI stage.
- Requiring mutation proof for ordinary unit tests, where the red phase of TDD already supplies it.
- Changing `test-engineer`'s or `developer`'s hard rules beyond the guard-test case.

## Acceptance Criteria

- AC1: Given `.claude/agents/code-reviewer.md`, when a reviewer reads it, then it requires mutation
  proof for regression-guard tests and specifies the report must name the reintroduced defect and
  quote the observed failure output.
- AC2: Given `.claude/agents/code-reviewer.md`, when a mutation check is impossible for a given guard
  (for example it asserts on a remote state), then the file directs the reviewer to say so explicitly
  rather than omit the step silently.
- AC3: Given `.claude/rules/testing.md`, when a test author reads it, then it states that a
  regression-guard test must be observed failing against the reintroduced defect before the story is
  considered complete, and defines the term.
- AC4: Given the guidance, when a reader asks what a vacuous guard looks like, then the worked example
  cites PUB-066's pathspec-wider-than-matcher case and the one-line mutation that exposed it.
- AC5: Given the mutation is performed in a working tree, when the check finishes, then the guidance
  requires the tree be restored (PUB-066's review used a detached worktree; a staged scratch file
  removed afterwards also worked).

## Implementation Notes

Documentation and agent-instruction only; no `publisher_v2/src` or test code changes, so there is no
pytest AC here and no coverage impact. Keep the addition short — the existing agent files are terse
and a long insert will be skimmed.

`.claude/rules/testing.md` already says "never blindly adjust tests to make them pass". This is the
mirror image: never accept a test that cannot fail. Placing them together is deliberate.

## Risks

- **Ritual compliance.** A reviewer could claim a mutation check it did not run. AC1's requirement to
  quote the actual failure output is the mitigation: an invented quote is a fabrication, not an
  omission, and is far more visible in review.
- Some cost per review. Bounded — the PUB-066 check was a two-line scratch file and one pytest run.

## Success Metrics

- No regression-guard test reaches `main` without a recorded mutation result in its item's summary or
  the reviewer's report.

## Related

- PUB-066 (#245) is the worked example; its summary records both the vacuous-matcher find and the
  fence-toggle find.
