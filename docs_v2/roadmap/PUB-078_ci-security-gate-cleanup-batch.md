# PUB-078: CI Security-Gate Cleanup Batch — SHA-Pin `code-quality.yml`, Bandit's Alembic Gap, pip-audit Drift

| Field | Value |
|-------|-------|
| **ID** | PUB-078 |
| **Category** | Ops |
| **Priority** | P2 |
| **Effort** | S |
| **Status** | Proposal |
| **Dependencies** | PUB-055 (merged, #236) |
| **Supersedes** | PUB-067, PUB-068, PUB-069 |

## User Story

As a maintainer, I want every action `code-quality.yml` runs to be SHA-pinned, every shipped source
file covered by bandit, and the `pip-audit` version pin declared in exactly one place CI can check,
so that the three small gaps PUB-055 knowingly left open close in one reviewable batch instead of
three separate PRs that each touch the same helpers in `test_ci_security_gates.py`.

## Problem

PUB-055 SHA-pinned every action in `security-scan.yml` and `secret-scan.yml`, and its own summary
called `code-quality.yml` "the natural next place to apply the same policy" — it was left tag-pinned
because it was out of scope, not because it was safe to skip. Since #229, `code-quality.yml` runs
the `pre-commit` job, which is where bandit and detect-secrets actually block; in substance
it is a security gate whose actions can still move underneath us. It also still carries a comment at
line 55 describing the `bandit -r .` step that #236 deleted from `security-scan.yml`.

Two smaller gaps sit next to it, found during the same audit:

1. **Bandit's scan root has a literal hole.** `.pre-commit-config.yaml` runs bandit with
   `-r publisher_v2/src scripts`. `publisher_v2/alembic/env.py` and
   `publisher_v2/alembic/versions/00{1,2,3}_*.py` are four shipped, non-archived source files no
   bandit invocation covers. Nothing that was *enforced* became unenforced — the deleted
   `security-scan.yml` step was `|| true` and could never fail a build — but the gap is real now that
   `pre-commit`'s bandit run genuinely blocks.
2. **`pip-audit==2.10.1` is typed out by hand in five places**: `.github/workflows/security-scan.yml`
   (the gate), `Makefile` (`security:` target), `SECURITY.md` (local reproduction),
   `.github/DEVELOPMENT.md` (contributor docs), and `scripts/pip_audit_ignore.py`'s docstring. A
   version bump is a five-site edit, and missing one is silent: CI and a local reproduction would
   audit with different tool versions and could disagree — the exact drift PUB-055 exists to remove.

All three are small, mechanical, and touch the same tooling PUB-055 built
(`test_ci_security_gates.py`'s SHA-pin parser, the pre-commit config, the security docs) — batching
them avoids three separate reviewers relearning the same helper file.

## Desired Outcome

Every `uses:` in `code-quality.yml` is pinned by 40-character commit SHA with the referenced tag in
a trailing comment, on the same terms PUB-055 established, and its stale line-55 comment is gone.
Bandit's scan roots cover the shipped source tree with no unexplained omission. The `pip-audit`
version is declared once, or a test asserts every occurrence agrees and fails on drift.

## Scope

**In scope:**
- SHA-pin every `uses:` in `code-quality.yml`; remove the stale `bandit -r .` comment at (historically)
  line 55; extend `test_every_action_in_the_security_workflows_is_pinned_by_sha` (or a sibling) to
  cover this file — reuse its existing flow-style-mapping and comment-requirement handling rather than
  duplicating the parser.
- Add `publisher_v2/alembic` to the bandit hook's `-r` args in `.pre-commit-config.yaml`; run
  `uv run pre-commit run bandit --all-files` and triage whatever it reports — fix real findings, or add
  a justified `# nosec` matching the existing convention in `config/orchestrator_client.py`,
  `web/service.py` and `services/ai.py`.
- Either a single declared `pip-audit` version the workflow and Makefile both read, or — the likely
  better trade per PUB-069's own Notes — a pytest function asserting all five occurrences agree, which
  needs no new indirection across a workflow, a Makefile and a docstring.

**Out of scope:**
- Bumping any action's major version while pinning — same rule PUB-055 followed.
- `caption-eval-nightly.yml`, which documents its own tag-vs-SHA policy.
- `publisher_v2/tests/**` (B101 assert noise by nature) and `code_v1/**` (archived, never edited) for
  the bandit scan-root change.
- Changing which tool runs, or how it is invoked, for the pip-audit item.

## Acceptance Criteria

- AC1: Every `uses:` value in `code-quality.yml` matches `<owner>/<repo>@<40-hex>` with a version
  comment on the same or next line, asserted by a named pytest function.
- AC2: No comment in `code-quality.yml` describes a step that no longer exists.
- AC3: `uv run pre-commit run bandit --all-files` covers `publisher_v2/alembic` and passes.
- AC4: Any bandit finding under `publisher_v2/alembic` is either fixed or carries a justified
  `# nosec` with a reason, matching the existing convention.
- AC5: A pytest function asserts every occurrence of a `pip-audit==<version>` spec in tracked files
  names the same version, and fails if any one drifts.
- AC6: Bumping the version in the canonical place (or in all five places, if the test-only approach is
  chosen) leaves the suite green.
- AC7: Given this item ships, when its implementing PR(s) merge, then #204 is closed with
  `Closes #204` in the PR body — SHA-pinning the remaining tag-pinned actions was its last open
  criterion now that PUB-055 and PUB-066 have merged.

## Implementation Notes

- Reuse the helpers in `publisher_v2/tests/test_ci_security_gates.py` for AC1/AC2 rather than copying
  the parser — it was hardened against 11 specific mutations; prefer widening its file list.
- The bandit scan-root change (AC3/AC4) and the SHA-pin change (AC1/AC2/AC7) are independent files and
  can land as two small PRs in either order within this item; the pip-audit test (AC5/AC6) is fully
  independent of both and can land separately too. "One item" tracks the batch; it does not require
  one PR.
- Decide the pip-audit approach (shared declaration vs. drift test) during implementation, per
  PUB-069's original Notes — the test-only approach is likely sufficient.

## Risks

- A too-eager bandit pass over `alembic/` could surface unrelated pre-existing findings; triage each
  on its own merits rather than blanket-suppressing.

## Success Metrics

- Zero tag-pinned actions remain in any workflow that gates a merge.
- A `pip-audit` version bump is a one-site edit, or a drifted second site fails CI immediately.

## Related

- Parent tracker [#243](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/243) · PUB-055
  (#236) · #229
- [#204](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/204) is closed by this item
  (its last open criterion)
- Supersedes [PUB-067](archive/PUB-067_sha-pin-code-quality-workflow.md),
  [PUB-068](archive/PUB-068_bandit-alembic-scan-root.md),
  [PUB-069](archive/PUB-069_pip-audit-version-single-source.md) — each is small, independent of the others,
  and touches the same PUB-055 tooling; batched here into one tracked item so a maintainer picks up
  one spec instead of three near-identical ones. No scope was added or removed in the merge; every AC
  above traces to an AC in one of the three originals.

- [#295](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/295) (CI/tooling duplication), once suggested for folding in here, is done by [PUB-084](PUB-084_dry-review-standalone-batch.md) wave 2b instead. After it, the per-job setup steps sit in one local composite action (`.github/actions/setup`), so AC1 pins that action's `uses:` once rather than six copies; each job's own `actions/checkout` still needs pinning.

## Change Log

- 2026-09-27 — Created by merging PUB-067, PUB-068 and PUB-069 at the user's request to reduce the
  number of separately-tracked security roadmap items (12 → fewer, grouped by shared file/tooling).
- 2026-09-27 — Noted that #295 is delivered by PUB-084 wave 2b and what that changes for AC1.
- 2026-09-28 — gitleaks is local-only since PUB-085 (#303).
