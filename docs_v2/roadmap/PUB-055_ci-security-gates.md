# PUB-055: CI Security Gates

| Field | Value |
|-------|-------|
| **ID** | PUB-055 |
| **Category** | Ops |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Proposal |
| **Dependencies** | — |

## User Story

As a platform maintainer, I want a vulnerable dependency, a bandit finding or a mutable action reference to fail CI, so that the dependency check done by hand in the 2026-09-21 review stays true without anyone repeating it.

## Problem

`.github/workflows/security-scan.yml:169-178` runs `pip-audit ... || true` with `continue-on-error: true`, `safety check ... || true` (a deprecated command) and `bandit ... || true`. `secret-scan.yml:118` and `security-scan.yml:190` use `trufflesecurity/trufflehog@main`, a mutable ref; every other action is pinned by major tag. `dependency-review-action@v3` is the only blocking gate and only on PRs. GitGuardian is `continue-on-error`. There is no `.github/dependabot.yml`. #78 made the test and mypy jobs fail for real; the security jobs were not on that list. The review checked `uv.lock` against known advisories (fastapi 0.124.4, starlette 0.49.3, python-multipart 0.0.26, authlib 1.6.6, pillow 11.3.0, jinja2 3.1.6, current) by hand, once.

## Desired Outcome

A deliberately vulnerable pin on a branch fails CI while `main` is green. No mutable action refs. Dependabot opens weekly grouped PRs. A test asserts the gates stay blocking.

## Scope

**In scope:**
- pip-audit blocking with an ignore file naming each accepted advisory, reason and expiry
- bandit blocking at medium severity and confidence
- `safety scan` or removal of safety as a duplicate (PR states which)
- Every action pinned by commit SHA with the version in a comment
- `.github/dependabot.yml`: weekly, pip and github-actions, grouped by minor and patch
- `tests/test_ci_security_gates.py` parsing the workflows: no `|| true` or `continue-on-error` on security steps; every `uses:` is a 40-character SHA
- `SECURITY.md` describes the gates and the ignore-list process

**Out of scope:**
- Changing which scanners run
- Coverage thresholds (done in #141)

## Acceptance Criteria

- AC1: Given a branch pinning an old `jinja2`, when CI runs, then the pip-audit job fails; the run is linked in the PR body and the pin reverted
- AC2: Given `main`, when CI runs, then every security job passes
- AC3: Given the workflow files, when the gate test runs, then no security step carries `|| true` or `continue-on-error` and every `uses:` is a SHA
- AC4: Given the Dependabot config, when a week passes, then grouped PRs for pip and actions are opened
- AC5: Given an accepted advisory, when it is added to the ignore file, then it carries a reason and an expiry date, and the gate test fails on an expired entry

## Implementation Notes

- Sub-issue #204, one PR.
- Keep the existing `# nosec` justifications; bandit at `-ll` matches them.

## Risks

- The first blocking run may surface an advisory with no fix; the ignore file with expiry is the release valve, not `continue-on-error`.

## Success Metrics

- Time from advisory publication to a Dependabot PR under one week.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issue [#204](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/204)
- Prior fixes #78 (CI actually failing), #141 (coverage gate), #166 (pre-commit toolchain)
