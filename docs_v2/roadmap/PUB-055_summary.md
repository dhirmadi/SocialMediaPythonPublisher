# PUB-055 — CI Security Gates: Implementation Summary

**Status:** Implementation Complete — merge gated on a prerequisite dependency-upgrade PR (see Notes)
**Date:** 2026-09-26

## Files Changed

| File | Change |
|------|--------|
| `.github/workflows/security-scan.yml` | Deleted the `safety` and `bandit` steps; pip-audit made blocking (`set -euo pipefail`, ignore-file wiring, no `\|\| true`, no `continue-on-error`); `bandit-report.json` dropped from the artifact path; GitGuardian given a job-level-`env:`-backed presence guard replacing `continue-on-error: true`; all 6 `uses:` SHA-pinned |
| `.github/workflows/secret-scan.yml` | `actions/checkout` and `trufflehog` SHA-pinned; obsolete "pin to a SHA" advisory comment replaced |
| `.github/dependabot.yml` | **New** — weekly `pip` + `github-actions`, each grouped on minor/patch |
| `.github/pip-audit-ignore.toml` | **New** — header comment only, zero entries |
| `scripts/pip_audit_ignore.py` | **New** — `load_ignore_entries()` + CLI; validates `id`/`reason`/`expires`, fails closed on expiry, malformed TOML, and a missing file |
| `publisher_v2/tests/test_ci_security_gates.py` | **New** — AC3/AC4/AC5 |
| `publisher_v2/tests/test_pip_audit_ignore.py` | **New** — AC6 + CLI fail-closed contract |
| `pyproject.toml`, `uv.lock` | `safety>=3.2.0` removed from the dev group (286 lock lines, 15 transitive deps). **Nothing added.** |
| `SECURITY.md` | "Security Scanning" rewritten: real gates + the ignore-list process |
| `Makefile` | `security:` target rewritten — last live `safety` caller; `\|\| true` removed |
| `.github/DEVELOPMENT.md` | Contributor `safety check` instructions replaced |
| `docs_v2/09_Reviews/QUALITY_METRICS.md` | Dependency-audit row renamed off `safety check` |
| `.secrets.baseline` | Mechanical detect-secrets regeneration (line shift + timestamp only) |

## Acceptance Criteria

- [ ] **AC1** — vulnerable pin fails the pip-audit job. **Not yet verified** — requires a live CI run; blocked on the prerequisite upgrade PR.
- [ ] **AC2** — every job green on main after merge. **Not yet verified** — same reason; would currently fail on the pre-existing advisory backlog.
- [x] **AC3** — `test_no_security_step_swallows_a_failure`
- [x] **AC4** — `test_every_action_in_the_security_workflows_is_pinned_by_sha`
- [x] **AC5** — `test_dependabot_config_groups_weekly_pip_and_actions_updates`
- [x] **AC6** — `test_an_expired_entry_raises_instead_of_silently_passing`, `test_unexpired_entries_yield_their_ignore_vuln_flags`

All five handoff-mandated test names exist verbatim. Ten further tests were added: expiry-boundary, the four `ValueError` branches, no-`ignore`-key, and five CLI fail-closed cases.

## Test Results

```
1862 passed, 1 skipped
```

## Quality Gates

| Gate | Result |
|------|--------|
| Format (`ruff format --check`) | ✅ 254 files already formatted |
| Lint (`ruff check`) | ✅ All checks passed |
| Type check (`mypy`) | ✅ no issues in 65 source files |
| Tests | ✅ 1862 passed, 1 skipped |
| Coverage | ✅ 93.01% (gate 85%) |

## Subagent Verdicts

- `test-engineer` (Red): 10 tests, each confirmed failing for the right reason.
- `developer` (Green): implemented; reported the Makefile `safety` decay itself.
- `code-reviewer` (round 2, adversarial): **BLOCKED → resolved.** Proved by mutation that the AC3/AC4/AC5 tests could not detect the gate being deleted outright, a `${{ }}`-expressed `continue-on-error`, an appended `exit 0`, the audit re-pointed at `/dev/null`, an unpinned tool, a flow-style `uses:`, or a neutered Dependabot config — 11 surviving mutations. Also found the audit set included pip-audit's own tree, the trufflehog SHA pinning only the wrapper, and the inert Dependabot `pip` half. All fixed; 11/11 mutations now fail.
- `code-reviewer` (round 1): **BLOCKED → resolved.** Caught `uvx pip-audit` auditing pip-audit's own 29-package tool venv instead of the project's 113. Also proved two AC6 assertions tautological by mutation. Both fixed and re-verified.
- `security-auditor`: **BLOCKED → resolved.** Same blocker, independently found by execution (0 findings via `uvx` vs 103 against the real environment). Confirmed secrets handling clean, ignore-list fails closed, SHA pins exact, bandit enforcement strictly improved.

## Notes

### Deviations from spec

1. **`uvx --from 'pip-audit==2.10.1' pip-audit --no-deps --disable-pip -r <uv export>`**, not the spec's `uv run pip-audit`. `pip-audit` was never a declared dependency, so the pre-existing step was failing on a missing binary under `|| true` — the gate had never run. An initial `uvx` attempt (Lead error, user-approved on a wrong recommendation) was worse: it audits pip-audit's own tool venv. Both reviewers caught it. A second attempt (`uv run --with`) audited 113 packages — the project's 93 plus pip-audit's own 19, so an advisory in `pip` itself would have red-lined main. The committed form exports `uv.lock` (`--frozen`, which also fails on a stale lock) and audits exactly those 93. No declared dependency is added; the version pin closes the "unpinned tool decides pass/fail" gap.

5. **Both trufflehog steps pin `version: "3.97.9"`.** The action is a composite wrapper around `docker run "$IMAGE:$VERSION"` defaulting to `latest`, so a SHA pin alone left the actual scanner floating.
6. **A `uv` Dependabot ecosystem was added alongside `pip`.** The spec mandates `pip` and AC5 asserts it, but `pip` cannot read `uv.lock` and every direct dependency is a bare `>=` floor, so that half bumps nothing. `pip` is retained for the contract; `uv` is what will actually fire.
2. **`Makefile` added to scope** — held the last live `safety check` caller.
3. **`.github/DEVELOPMENT.md` + `QUALITY_METRICS.md`** — same stale-`safety` defect one layer out; user approved folding in.
4. **AC6 CLI coverage** is asserted via in-process `main(["--path", ...])` + `capsys`, not subprocess, honoring the spec's Mock-boundaries table.

### Prerequisite: dependency-upgrade PR (blocks AC1/AC2)

Making pip-audit genuinely blocking revealed **103 advisories as pip-audit counts them (56 unique package/advisory pairs) across 16 packages**, 12 of them production dependencies, all with fixes released:

| Package | Current | Advisories | Fix |
|---|---|---|---|
| pillow | 11.3.0 | 18 | 12.3.0 |
| authlib | 1.6.6 | 7 | 1.6.9 |
| cryptography | 46.0.3 | 7 | 50.0.0 |
| starlette | 0.49.3 | 5 | 1.3.1 |
| python-multipart | 0.0.26 | 4 | 0.0.31 |
| urllib3 | 2.6.2 | 3 | 2.7.0 |
| anyio | 4.12.0 | 2 | 4.14.2 |
| filelock (dev) | 3.19.1 | 2 | 3.20.3 |
| click, idna, instagrapi, python-dotenv, requests | | 1 each | |
| pygments, pytest, virtualenv (dev) | | 1 each | |

`authlib` and `cryptography` sit on the Auth0 admin-cookie path. The spec's Problem section recorded these as current as of the 2026-09-21 hand review; that check has since gone stale — exactly the decay this item exists to stop.

**Agreed sequencing:** a dependency-upgrade PR lands first, then this branch merges fully blocking and green, with AC1/AC2 verified there. Rejected alternatives: shipping the gate non-blocking (would require weakening AC3's test, and the gate would sit unenforced), and seeding the ignore file with ~16 entries (ships a hardening PR with a 56-advisory hole).

### Tracked follow-ups (deliberately out of scope)

- `code-quality.yml:55` comment describes the bandit step this PR deleted; and that workflow is entirely tag-pinned with zero SHA pins — the natural next target for this item's pinning policy.
- `.pre-commit-config.yaml` bandit roots omit `publisher_v2/alembic` (4 shipped source files). No enforcement was lost — the deleted step was `|| true` — but it is a literal scan-root gap.
- AC5's wording mandates the `pip` ecosystem, which is inert for this repo. A `uv` entry was added alongside it; the spec should be amended so the test asserts the ecosystem that actually works. Confirm on the first push that GitHub accepts `uv` — it is listed in Dependabot's options reference but absent from the ecosystems summary page.
- `SECURITY.md`'s "CI enforces two blocking gates" counts pip-audit and bandit; detect-secrets and gitleaks also block via the pre-commit job since #229.
- `pip-audit==2.10.1` is pinned in four places with no single source of truth.
