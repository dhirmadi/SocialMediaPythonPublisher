# PUB-085 — Gitleaks CI Honesty and Admin-UI Behaviour Coverage: Implementation Summary

**Status:** In Progress (part A complete; part B in review)
**Date:** 2026-09-28

## Part A — Gitleaks CI honesty (#303)

### Files Changed

- `.github/workflows/code-quality.yml` — the `pre-commit` job's "Run every pre-commit hook" step sets `env: SKIP: gitleaks`, with a comment saying why: the pinned hook (`gitleaks git --pre-commit --staged`) diffs the index against HEAD, and a fresh CI checkout's index equals HEAD, so it could never fail in CI. The job header no longer lists gitleaks among hooks that "run nowhere else", and its false claim that `security-scan.yml` runs bandit with `|| true` is gone (no workflow runs bandit).
- `SECURITY.md` — "Security Scanning" now names three blocking gates. The secret-scanning bullet says gitleaks is a local hook on `git commit` that CI skips; that TruffleHog scans every PR and every push to `main`, plus a weekly or manual full-history scan reporting verified findings only; that detect-secrets scans all files in the `pre-commit` job; and that the GitGuardian GitHub App scans PRs, while the `ggshield` step in `security-scan.yml` is skipped because the repo has no `GITGUARDIAN_API_KEY` secret.
- `publisher_v2/tests/test_ci_security_gates.py` — AC1 and AC2 tests.
- `docs_v2/roadmap/PUB-078_*` — its stale "gitleaks actually blocks" claim corrected; Change Log line added.

### Acceptance Criteria

- [x] AC1 — the CI job skips gitleaks and says why; no comment claims CI enforces it (test: `test_ci_precommit_job_skips_gitleaks_and_says_why`)
- [x] AC2 — the hook stays configured; SECURITY.md describes gitleaks as a local `git commit` hook and names the CI scanners (test: `test_gitleaks_is_documented_as_a_local_hook`). It checks individual sentences: "pre-commit" does not satisfy "commit", and any sentence claiming CI enforcement fails unless it says the hook is skipped.

### Verification

- Mutations: removing `SKIP`, restoring the old "Four of its hooks … gitleaks … nowhere else" comment, re-adding gitleaks to the list, removing the why-comment, `SKIP: gitleaks-docker`, dropping TruffleHog from SECURITY.md, and SECURITY.md sentences calling gitleaks a CI gate (including "local hook and a blocking CI gate") all fail.
- `SKIP=gitleaks` skips only that hook id; detect-secrets, bandit, pydocstyle and ruff still run.
- actionlint clean; 12 tests in the file pass; default suite green.

### Subagent Verdicts

- `code-reviewer`: PASS WITH NITS. Applied: the vacuous "commit" match in AC2 tightened; GitGuardian's real state described (App on PRs, workflow step skipped); "two blocking gates" corrected; TruffleHog's push trigger limited to `main`; PUB-078's stale claim fixed.
- `security-auditor`: PASS WITH NITS. From the gitleaks v8.22.1 source, the CI run scanned nothing, so skipping it loses no coverage. Wording nits applied.

### Linked Issues

- #303 — closed by the part A PR
