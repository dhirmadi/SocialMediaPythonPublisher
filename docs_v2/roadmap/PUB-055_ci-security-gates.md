# PUB-055: CI Security Gates

| Field | Value |
|-------|-------|
| **ID** | PUB-055 |
| **Category** | Ops |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Implementation Complete |
| **Dependencies** | — |

## User Story

As a platform maintainer, I want a vulnerable dependency, a bandit finding, a leaked secret or a mutable action reference to fail CI, so that the dependency check done by hand in the 2026-09-21 review stays true without anyone repeating it.

## Problem

`.github/workflows/security-scan.yml:169-178` runs `pip-audit ... || true` with `continue-on-error: true`, `safety check ... || true` (a deprecated command) and `bandit ... || true`. `secret-scan.yml:118` and `security-scan.yml:190` use `trufflesecurity/trufflehog@main`, a mutable ref; every other action is pinned by major tag. `dependency-review-action@v3` is the only blocking gate and only on PRs. GitGuardian is `continue-on-error`. There is no `.github/dependabot.yml`. #78 made the test and mypy jobs fail for real; the security jobs were not on that list. The review checked `uv.lock` against known advisories (fastapi 0.124.4, starlette 0.49.3, python-multipart 0.0.26, authlib 1.6.6, pillow 11.3.0, jinja2 3.1.6, current) by hand, once.

## Desired Outcome

A deliberately vulnerable pin on a branch fails CI while `main` is green. No mutable action refs. Dependabot opens weekly grouped PRs. A test asserts the gates stay blocking.

## Scope

**In scope:**
- pip-audit blocking, with `--ignore-vuln` flags for accepted advisories sourced from
  `.github/pip-audit-ignore.toml` (see Implementation Notes for the exact schema and the
  `scripts/pip_audit_ignore.py` helper that validates and reads it)
- Remove the redundant `safety check` step from `security-scan.yml`, and prune `safety>=3.2.0`
  from `pyproject.toml`'s dev dependency group in the same PR (a dependency nobody imports is the
  same kind of decay this item exists to close off). `pip-audit` (OSV-backed, actively
  maintained) is the one blocking dependency-vulnerability gate; `safety check` is deprecated and
  its replacement (`safety scan`) needs a Safety CLI account, which this item does not introduce.
  **This is a scope decision, not a de-duplication of identical coverage** — `safety` (Safety DB)
  and `pip-audit` (OSV) cover different advisory sources, so dropping `safety` is a real (small,
  deliberate) reduction in scanner coverage, called out here explicitly rather than smuggled in
  under "de-duplication." It is made now, not left to the implementing PR, so the gate test has a
  fixed target — flagged explicitly in Risks below rather than left implicit.
  `SECURITY.md`'s existing "Security Scanning" contributor bullet (`pip install safety bandit;
  safety check; bandit -r . ...`) currently recommends the exact commands being deleted from CI;
  rewrite it in the same PR so the doc doesn't contradict its own rationale.
- Bandit: **do not** re-add a bandit-blocking mechanism — `code-quality.yml`'s `pre-commit` job
  (added by #229, see Change Log) already blocks on bandit findings against `publisher_v2/src`
  and `scripts`, honoring the existing `# nosec` justifications, using bandit's default
  severity/confidence (not `-ll`/`-ii` — that framing predates #229 and is stale). This item's
  only bandit-related task is deleting `security-scan.yml`'s now-redundant, non-blocking
  `bandit -r . ... || true` step so there is exactly one bandit gate, not two with different args
  and different scan roots.
- Every remaining `uses:` step in `security-scan.yml` and `secret-scan.yml` (the two files this
  item's Problem section is about) pinned by 40-character commit SHA with the referenced tag in a
  trailing comment (e.g. `uses: actions/checkout@<sha>  # v4.x.y`). Pin to the SHA of whichever
  tag is **currently** referenced — do not bump major versions in this same change (e.g.
  `dependency-review-action@v3` is several majors behind `@v5` at hardening time; upgrading it is
  a separate, out-of-scope change, same principle as "changing which scanners run"). `code-
  quality.yml` and `caption-eval-nightly.yml` are untouched by this item — the latter already
  documents its own tag-vs-SHA policy and is out of scope here.
- `trufflesecurity/trufflehog@main` (the two mutable refs named in Problem) pinned to a commit SHA
  in both `security-scan.yml` and `secret-scan.yml`, same as every other action in those files.
- GitGuardian's step in `security-scan.yml` loses `continue-on-error: true`, but gains a
  presence-guard on `GITGUARDIAN_API_KEY` instead of running unconditionally. **`secrets.*` is
  not a valid context in step-level `if:`** (GitHub's context-availability table excludes
  `secrets` from `jobs.<job_id>.steps.if`; it is only readable from `env:` blocks) — the guard
  must go through a job-level `env:` first:
  ```yaml
  secret-scanning:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    env:
      GITGUARDIAN_API_KEY: ${{ secrets.GITGUARDIAN_API_KEY }}
    steps:
      - name: Checkout code
        uses: actions/checkout@<sha>  # v4.x.y
        with:
          fetch-depth: 0
      - name: GitGuardian scan
        if: ${{ env.GITGUARDIAN_API_KEY != '' }}
        uses: GitGuardian/ggshield-action@<sha>  # v1.x.y
        env:
          GITGUARDIAN_API_KEY: ${{ env.GITGUARDIAN_API_KEY }}
          GITHUB_PUSH_BEFORE_SHA: ${{ github.event.before }}
          GITHUB_PUSH_BASE_SHA: ${{ github.event.base }}
          GITHUB_DEFAULT_BRANCH: ${{ github.event.repository.default_branch }}
  ```
  Hardening recorded **no** `GITGUARDIAN_API_KEY` secret on this repo (via `gh secret list`), on
  the reasoning that making the step unconditionally blocking would fail every run on an auth
  error rather than a real finding. **That was wrong** — the GitGuardian check ran and passed in
  2s on PR #235 (2026-09-26), so a key *is* configured. The guard is still the right shape: it
  blocks for real today, and degrades to a clean skip if the key is ever removed or rotated out.
  Only the premise about the key's absence was incorrect; see Risks.
- `.github/dependabot.yml`: weekly, `pip` and `github-actions` ecosystems, each grouped by
  `update-types: ["minor", "patch"]` (major bumps stay ungrouped so they get individual review)
- `tests/test_ci_security_gates.py` parsing `security-scan.yml`/`secret-scan.yml`: no security
  step carries `|| true` or `continue-on-error` (except the GitGuardian presence-guard, which is
  an `if:`, not a `continue-on-error:`); every `uses:` in those two files is a 40-character SHA
  with a version comment; `.github/dependabot.yml` has the weekly/grouped config described above
- `publisher_v2/tests/test_pip_audit_ignore.py` covering `scripts/pip_audit_ignore.py`'s schema
  validation and expiry check (see Implementation Notes)
- `SECURITY.md` describes the gates and the ignore-list process

**Out of scope:**
- Changing which scanners run, **except** removing `safety` (see the Scope bullet above and
  Risks — this is a deliberate, called-out exception to this bullet, not something this bullet
  silently permits)
- Migrating to `safety scan` (would need a new `SAFETY_API_KEY` secret and account)
- Bumping any action's major version, or `dependency-review-action`'s `fail-on-severity`
- Touching `code-quality.yml` or `caption-eval-nightly.yml`
- Coverage thresholds (done in #141)

## Acceptance Criteria

AC1 and AC2 are verification steps, not `pytest` ACs — do not invent test names for them (same
pattern as PUB-052's AC9/AC10, though the reason differs: PUB-052's are an owner's subjective
judgment call that no code can substitute for; these are deterministic facts about a live
GitHub Actions run — but automating them would mean either (a) mocking pip-audit's subprocess
call, which would just re-assert AC3's static "no `|| true`" check under a different name without
exercising pip-audit's real vulnerability database, or (b) giving the test suite network/
subprocess access to a live runner, which the Mock boundaries table below deliberately rules out
for this item's tests). They are proven once, live, as part of delivering this item's PR, not as
a permanent regression test (a permanently-vulnerable pin would defeat its own purpose, and "CI
is green on main" cannot be asserted from within the test suite that runs before the merge it
describes).

- AC1: Given a branch that pins a `jinja2` version with a known advisory (e.g. `jinja2==2.11.3`),
  when CI runs on that branch, then the pip-audit job fails with that advisory in its output.
  **Verification:** push the pin on a scratch branch/PR as part of implementing this item, link
  the failing run's URL in the delivery PR body, then revert the pin before merge — do not leave
  a permanently-vulnerable pin in history past that PR.
  **Verified 2026-09-26 (PR #237, closed unmerged, branch deleted):**
  [run 36262301101](https://github.com/dhirmadi/SocialMediaPythonPublisher/actions/runs/36262301101)
  — `Found 6 known vulnerabilities in 1 package`, exit 1. Note the suggested `jinja2==2.11.3` is
  **unresolvable in this repo**: a transitive requirement demands `jinja2>=3.1.0`, so `uv lock`
  refuses and nothing reaches CI. `urllib3==2.6.2` (PYSEC-2026-141/142/1996) was substituted. Any
  known-vulnerable, *resolvable* pin satisfies this AC — do not retry the jinja2 pin.
- AC2: Given `main` after this item merges, when CI runs, then every job in `security-scan.yml`
  and `secret-scan.yml` passes. **Corrected 2026-09-26:** this AC originally expected GitGuardian
  to pass *by skipping*, because hardening recorded no `GITGUARDIAN_API_KEY`. A key is in fact
  configured (it passed in 2s on PR #235), so that step genuinely runs and must pass on its own
  merits — a stricter outcome than the original wording, and the intended end state.
  **Verification:** check the Actions run for the merge commit; link it in the delivery PR body.
  **Verified 2026-09-26:** merge commit `c8febb9` — `Security Scan`, `Secret scan` and
  `Code Quality` all succeeded
  ([run 36262537037](https://github.com/dhirmadi/SocialMediaPythonPublisher/actions/runs/36262537037)).
- AC3: Given `security-scan.yml` and `secret-scan.yml`, when
  `publisher_v2/tests/test_ci_security_gates.py::test_no_security_step_swallows_a_failure` runs,
  then it finds no `|| true` and no `continue-on-error: true` on any step in either file (the
  GitGuardian step's `if: env.GITGUARDIAN_API_KEY != ''` guard does not count as either), and
  finds no step invoking `safety`.
- AC4: Given `security-scan.yml` and `secret-scan.yml`, when
  `publisher_v2/tests/test_ci_security_gates.py::test_every_action_in_the_security_workflows_is_pinned_by_sha`
  runs, then every `uses:` value in both files matches `<owner>/<repo>@<40-hex-char-sha>` and is
  followed by a version comment on the same or next line.
- AC5: Given `.github/dependabot.yml`, when
  `publisher_v2/tests/test_ci_security_gates.py::test_dependabot_config_groups_weekly_pip_and_actions_updates`
  parses it, then it declares `pip` and `github-actions` ecosystems, each with
  `interval: "weekly"` and a `groups:` entry whose `update-types` includes `"minor"` and
  `"patch"`.
- AC6: Given an ignore-file entry (`.github/pip-audit-ignore.toml`, schema in Implementation
  Notes), when `scripts/pip_audit_ignore.py`'s loader runs, then an entry missing `reason` or
  `expires` raises, and `publisher_v2/tests/test_pip_audit_ignore.py::test_an_expired_entry_raises_instead_of_silently_passing`
  proves that an entry whose `expires` date is in the past raises rather than being silently
  applied; `test_pip_audit_ignore.py::test_unexpired_entries_yield_their_ignore_vuln_flags` proves
  a valid, unexpired entry produces the corresponding `--ignore-vuln <id>` argument.

## Implementation Notes

- Sub-issue #204, one PR.
- The existing `# nosec` justifications (`config/orchestrator_client.py`, `config/schema.py`,
  `web/service.py`, `web/app.py`, `services/ai.py`) are matched by the `pre-commit` job's bandit
  hook (`.pre-commit-config.yaml`, `-r publisher_v2/src scripts`, default severity/confidence —
  no `-ll`/`-ii`), not by anything this item adds. Do not add a second, differently-configured
  bandit invocation; just delete `security-scan.yml`'s.

### `.github/pip-audit-ignore.toml` schema and `scripts/pip_audit_ignore.py`

TOML, array-of-tables, one `[[ignore]]` per accepted advisory:

```toml
# Accepted advisories pip-audit must skip. Every entry needs a reason and an
# expiry date (ISO 8601, YYYY-MM-DD); the gate fails once `expires` has
# passed, forcing a re-review instead of a silent permanent skip.

[[ignore]]
id = "GHSA-xxxx-xxxx-xxxx"
reason = "Why this is accepted (no fix yet, code path unused, etc.)."
expires = "2026-12-31"
```

Start the committed file with just the header comment and no `[[ignore]]` entries — the
2026-09-21 review found nothing to ignore. A missing `ignore` key means zero entries, not a
parse error.

`scripts/pip_audit_ignore.py` (new, follows the existing `scripts/*.py` pattern, e.g.
`scripts/caption_eval.py`):
- `load_ignore_entries(path: Path, today: date | None = None) -> list[str]` — parses the TOML,
  raises `ValueError` (naming the offending entry's `id`) if any entry is missing `id`, `reason`,
  or `expires`, or if `today > expires` for any entry (default `today = date.today()`, injectable
  for tests). Returns the `id`s of entries that are not expired.
- CLI mode (`if __name__ == "__main__":`) prints `--ignore-vuln <id>` tokens (one per surviving
  entry, space-separated) to stdout on success, and exits non-zero with the `ValueError` message
  on stderr when validation fails — so the workflow step fails *before* pip-audit even runs if
  the ignore file itself is stale.
- Wire into `security-scan.yml`'s pip-audit step via command substitution, e.g.:
  ```yaml
  - name: Run pip-audit (dependency vulnerabilities)
    run: |
      IGNORE_ARGS=$(uv run python scripts/pip_audit_ignore.py)
      uv run pip-audit -f json -o pip-audit-report.json $IGNORE_ARGS
  ```
- Test it the way `test_caption_sample_script.py` tests `scripts/caption_sample.py`:
  `importlib.util.spec_from_file_location("pip_audit_ignore", REPO_ROOT / "scripts" /
  "pip_audit_ignore.py")` — `scripts/` has no `__init__.py`, so it is not an importable package.

### Files likely touched

| Area | Files to modify | Files to create |
|------|------------------|-------------------|
| Workflows | `.github/workflows/security-scan.yml` (drop `safety`/bandit steps and `bandit-report.json` from the artifact upload path alongside them, pin every `uses:`, SHA-pin trufflehog, add `pip-audit-ignore` wiring, guard GitGuardian per the job-level `env:` pattern above) | `.github/dependabot.yml` |
| Workflows | `.github/workflows/secret-scan.yml` (SHA-pin `actions/checkout` and `trufflehog`) | — |
| Ignore gate | — | `.github/pip-audit-ignore.toml`, `scripts/pip_audit_ignore.py` |
| Tests | — | `publisher_v2/tests/test_ci_security_gates.py`, `publisher_v2/tests/test_pip_audit_ignore.py` |
| Deps | `pyproject.toml` (remove `safety>=3.2.0` from the dev group) | — |
| Docs | `SECURITY.md` (describe the gates + ignore-list process; rewrite the "Security Scanning" contributor bullet that currently recommends `safety check`) | — |

### Mock boundaries

| External service | Mock strategy | Notes |
|-------------------|----------------|-------|
| None — `test_ci_security_gates.py` reads workflow/dependabot YAML as text/`yaml.safe_load` (PyYAML is already a dependency); no network, no subprocess against a real pip-audit/GitHub Actions run | — | Same pattern as `test_coverage_gate_config.py` |
| `scripts/pip_audit_ignore.py` | Pure function over a `tmp_path` fixture TOML file; inject `today` explicitly rather than freezing real time | No `unittest.mock.patch` needed |

## Risks

- The first blocking pip-audit run may surface an advisory with no fix; the ignore file with
  expiry is the release valve, not `continue-on-error`.
- `GITGUARDIAN_API_KEY` is not configured on this repo today. The presence-guard means the step
  skips (not fails) until someone adds the secret — that is intentional, but if the user wants
  GitGuardian blocking from day one, the secret must be added first (adding/rotating a production
  secret is a gated action per `AGENTS.md` — the agent implementing this item does not invent or
  set one).
- `dependency-review-action` is pinned at `@v3` while `@v5` is current at hardening time; pinning
  its `@v3` SHA preserves today's (already slightly stale) behavior rather than silently
  upgrading it inside a security-hardening PR.
- Removing the `safety` step is a real (small) reduction in scanner coverage, not a pure
  de-duplication — `safety` (Safety DB) and `pip-audit` (OSV) draw from different advisory
  sources. The operational reason (deprecated CLI command; `safety scan` needs an account this
  item doesn't want to introduce) is sound, but it is a scope decision the user should see stated
  plainly, not just infer from a Scope-bullet parenthetical: **if you'd rather keep a
  Safety-DB-backed gate, say so before implementation** — the alternative is migrating to
  `safety scan` with a `SAFETY_API_KEY`, which is a bigger, out-of-scope change (new secret, new
  account).
- `code-quality.yml`'s `pre-commit` job (added by #229) is, in substance, also a security gate
  now (bandit, detect-secrets, gitleaks all run there) and is entirely tag-pinned, with zero SHA
  pins. It is explicitly out of scope for this item (see Scope), but is the natural next place to
  apply the same SHA-pinning policy.

## Success Metrics

- Time from advisory publication to a Dependabot PR under one week.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issue [#204](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/204)
- Prior fixes #78 (CI actually failing), #141 (coverage gate), #166 (pre-commit toolchain)

## Change Log

- 2026-09-26 — Partially overtaken by #229, which added a blocking `pre-commit` job to `code-quality.yml` running all seventeen hooks. bandit now fails a build through that job, and detect-secrets, gitleaks and pydocstyle are enforced in CI for the first time (previously they ran only on clones where `pre-commit install` had been run, which was none). This does **not** close the item: `security-scan.yml`'s own `pip-audit`/`safety`/`bandit` steps are still `|| true`, the mutable `trufflehog@main` refs are unchanged, there is still no `.github/dependabot.yml`, and no test asserts the gates stay blocking. Re-scope the bandit bullet when this item is picked up — it is now about removing the `|| true` in `security-scan.yml` rather than making bandit block at all.
- 2026-09-26 — Hardened for Claude Code handoff (`/product-harden`). Rescoped the bandit bullet per the entry above. Resolved several ambiguities the original draft left implicit: (1) `safety` is removed outright rather than migrated, a real (small) reduction in scanner coverage flagged in Risks, not just de-duplication; (2) SHA-pinning is scoped to `security-scan.yml`/`secret-scan.yml` only, matching the Problem section's own line-number citations — `code-quality.yml`/`caption-eval-nightly.yml` are untouched; (3) GitGuardian's step gets a job-level-`env:`-backed presence guard instead of unconditional blocking, since this repo has no `GITGUARDIAN_API_KEY` configured today; (4) the ignore-file (`.github/pip-audit-ignore.toml`) and its validator (`scripts/pip_audit_ignore.py`) now have a concrete schema and contract so AC6 is pytest-testable rather than prose; (5) AC1/AC2 are marked as one-time manual verification, not permanent tests, since they describe live-CI facts this item's own network-free test policy can't assert from within `pytest`. An adversarial `architect-reviewer` pass caught one implementation-blocking error in the first draft (the illustrative GitGuardian guard used `secrets.*` directly in a step-level `if:`, which GitHub Actions does not support there) and several visibility gaps (safety-removal needed louder flagging; `pyproject.toml`'s now-orphaned `safety` dev dependency and `SECURITY.md`'s contributor-facing `safety check` recommendation were unaddressed) — all applied above. See `PUB-055_handoff.md` for the Claude Code contract.
- 2026-09-26 — Implemented (PR #236, stacked on #235). Two spec premises were corrected against
  live evidence rather than left to mislead: AC2's GitGuardian expectation (a key *is* configured,
  so the step blocks rather than skips), and the Scope note asserting the key's absence. Three
  deviations are recorded in `PUB-055_summary.md`: pip-audit runs against a `uv export --frozen`
  of the lock with a pinned tool version (the spec's `uv run pip-audit` could never have worked —
  pip-audit was not a declared dependency); `Makefile` was added to scope as the last live
  `safety` caller; and a `uv` Dependabot ecosystem was added alongside the spec-mandated `pip`
  one, which cannot read `uv.lock`. AC1/AC2 are verified live against PR #236.

## Post-merge findings (2026-09-26)

Three things the live runs exposed that the spec had wrong or could not have known.

### The workflow was disabled, so nothing in it ran at all

`Security Scan` was in state `disabled_inactivity`, last run 2026-07-27. GitHub auto-disables a
workflow carrying a `schedule:` trigger after roughly 60 days of repository inactivity, and it
disables the **whole workflow**, not just the cron. Re-enabled with `gh workflow enable
security-scan.yml`, which is the only reason this item's verification runs exist.

So the Problem section understates the situation. There were **three independent reasons** pip-audit
could never fail, any one of them sufficient on its own:

1. the workflow was disabled entirely;
2. `pip-audit` was never a declared dependency, so the step would have died on a missing binary;
3. `|| true` plus `continue-on-error: true` would have swallowed the result anyway.

**Known limitation.** `test_ci_security_gates.py` asserts the workflow *file* is correct and would
have passed happily throughout those two dormant months. Enablement is repository state, not file
content, so no test in this repo can detect a recurrence. The weekly scheduled run is the canary: if
it stops appearing in the Actions list, the workflow has been auto-disabled again.

### AC5's `pip` ecosystem is inert

Dependabot's `pip` updater cannot read `uv.lock`, and every direct dependency in `pyproject.toml` is
a bare `>=` floor that any release already satisfies, so it can bump nothing. A `uv` entry was added
alongside it and GitHub does accept that ecosystem name. AC5 and
`test_dependabot_config_groups_weekly_pip_and_actions_updates` still mandate `pip`; the criterion
should be amended to assert the ecosystem that actually maintains the lock. Tracked in PUB-066.

### Both Python updaters then failed for an unrelated, pre-existing reason

`pip` and `uv` abort on `/requirements.txt not found` — a dangling `-r` in a stale
`requirements-dev.txt` that predates the uv migration. This item's success metric (advisory to
Dependabot PR within a week) is therefore unmet for Python packages until PUB-066 lands.
