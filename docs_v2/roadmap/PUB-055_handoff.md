# Implementation Handoff: PUB-055 — CI Security Gates

**Hardened:** 2026-09-26
**Status:** Ready for implementation

## For Claude Code

### Test-first targets

AC1 and AC2 are **verification steps, not `pytest` ACs** — do not invent test names for them.
See the spec's Acceptance Criteria section for exactly what to do instead (push a scratch branch
with a deliberately vulnerable `jinja2` pin for AC1, link the failing run in the delivery PR body,
revert before merge; link the green Actions run on the merge commit for AC2).

| AC | Test file | Test name (exact function) |
|----|-----------|-----------------------------|
| AC1 | — | N/A — manual verification, see spec |
| AC2 | — | N/A — manual verification, see spec |
| AC3 | `publisher_v2/tests/test_ci_security_gates.py` | `test_no_security_step_swallows_a_failure` |
| AC4 | `publisher_v2/tests/test_ci_security_gates.py` | `test_every_action_in_the_security_workflows_is_pinned_by_sha` |
| AC5 | `publisher_v2/tests/test_ci_security_gates.py` | `test_dependabot_config_groups_weekly_pip_and_actions_updates` |
| AC6 | `publisher_v2/tests/test_pip_audit_ignore.py` | `test_an_expired_entry_raises_instead_of_silently_passing` |
| AC6 | `publisher_v2/tests/test_pip_audit_ignore.py` | `test_unexpired_entries_yield_their_ignore_vuln_flags` |

The **Test name** column is the exact `pytest` function name you must create — the only
spec-to-test traceability link this contract relies on. If a different name is genuinely
clearer, record the actual name used in `PUB-055_summary.md` next to the AC it satisfies.

### Sequencing / read-this-first

The roadmap item's own Change Log has two entries worth reading in full before starting:
1. The 2026-09-26 (first) entry explains why the **bandit** bullet is about *removing* a
   redundant, non-blocking step in `security-scan.yml`, not making bandit block for the first
   time — `code-quality.yml`'s `pre-commit` job (#229) already blocks on bandit.
2. The 2026-09-26 (second, hardening) entry summarizes every ambiguity resolved during
   `/product-harden`, including one implementation-blocking correction from the adversarial
   review (the GitGuardian guard's exact YAML shape — copy the block in the spec's Scope section
   verbatim, do not use `secrets.*` in a step-level `if:`).

### The four workflow-editing tasks (`security-scan.yml`, `secret-scan.yml`)

1. **Delete** the `safety` step and the `bandit` step from `security-scan.yml`'s `security-scan`
   job. Drop `bandit-report.json` from the "Upload security scan artifacts" step's `path:` list
   (keep `pip-audit-report.json`).
2. **Rewrite the pip-audit step** to consume `.github/pip-audit-ignore.toml` via
   `scripts/pip_audit_ignore.py` (new — see below) and drop `|| true` / `continue-on-error`:
   ```yaml
   - name: Run pip-audit (dependency vulnerabilities)
     run: |
       IGNORE_ARGS=$(uv run python scripts/pip_audit_ignore.py)
       uv run pip-audit -f json -o pip-audit-report.json $IGNORE_ARGS
   ```
3. **Rewrite the GitGuardian step** exactly per the YAML block in the spec's Scope section (job-
   level `env: GITGUARDIAN_API_KEY: ${{ secrets.GITGUARDIAN_API_KEY }}`, step-level
   `if: ${{ env.GITGUARDIAN_API_KEY != '' }}`, replacing `continue-on-error: true`). This applies
   to the `secret-scanning` job in `security-scan.yml`.
4. **SHA-pin every `uses:`** in `security-scan.yml` and `secret-scan.yml` (both jobs/steps in
   each file), each followed by a version comment, e.g. `uses: actions/checkout@<sha>  # v4.x.y`.
   Resolve each action's current tag to its SHA at implementation time (e.g.
   `gh api repos/<owner>/<repo>/git/refs/tags/<tag>`, or the GitHub UI's "Copy SHA" on the tag's
   commit) — do not bump any action's major version while doing this (spec's Out-of-scope). This
   includes both `trufflesecurity/trufflehog@main` refs (the two mutable refs named in Problem).
   `code-quality.yml` and `caption-eval-nightly.yml` are **not** touched by this item.

### `scripts/pip_audit_ignore.py` and `.github/pip-audit-ignore.toml` (AC6)

Full schema, function signature, CLI contract, and the committed file's starting content (header
comment only, zero `[[ignore]]` entries) are all specified in the spec's Implementation Notes —
follow that section exactly, it is the contract for this file's shape. Test-loading pattern:
`scripts/` has no `__init__.py`, so load it in tests the way
`publisher_v2/tests/test_caption_sample_script.py` loads `scripts/caption_sample.py` —
`importlib.util.spec_from_file_location(...)` + `exec_module`, not a normal import.

### `.github/dependabot.yml` (AC5)

```yaml
version: 2
updates:
  - package-ecosystem: "pip"
    directory: "/"
    schedule:
      interval: "weekly"
    groups:
      python-dependencies:
        update-types: ["minor", "patch"]
  - package-ecosystem: "github-actions"
    directory: "/"
    schedule:
      interval: "weekly"
    groups:
      github-actions:
        update-types: ["minor", "patch"]
```
Adjust group names/labels to taste, but the test asserts both ecosystems are present, each with
`interval: "weekly"` and a `groups:` entry whose `update-types` includes `"minor"` and `"patch"`.

### Other files this item touches

- `pyproject.toml`: remove `safety>=3.2.0` from the dev dependency group. Run `uv sync --group
  dev` afterward so `uv.lock` reflects the removal.
- `SECURITY.md`: rewrite the "Security Scanning" bullet under "For Contributors" (currently
  recommends `pip install safety bandit; safety check; bandit -r . ...`) to describe the actual
  gates (pip-audit with the ignore-file, bandit via the pre-commit hook) instead of the commands
  being deleted from CI. Also add a short description of the ignore-list process (Scope
  requirement) — point at `.github/pip-audit-ignore.toml`'s header comment for the exact schema
  rather than duplicating it.

### Mock boundaries

| External service | Mock strategy | Existing fixture/pattern |
|-------------------|----------------|----------------------------|
| None for `test_ci_security_gates.py` | Read workflow/`dependabot.yml` text and/or `yaml.safe_load` it (PyYAML is already a dependency — see `pyproject.toml`) | Same shape as `publisher_v2/tests/test_coverage_gate_config.py` (reads `.github/workflows/code-quality.yml` as text) |
| None for `test_pip_audit_ignore.py` | Call `load_ignore_entries(path, today=...)` directly against a `tmp_path` fixture TOML file; inject `today` rather than freezing real time | New — no existing fixture needed |

### Files likely touched

| Area | Files to modify | Files to create |
|------|------------------|-------------------|
| Workflows | `.github/workflows/security-scan.yml`, `.github/workflows/secret-scan.yml` | `.github/dependabot.yml` |
| Ignore gate | — | `.github/pip-audit-ignore.toml`, `scripts/pip_audit_ignore.py` |
| Tests | — | `publisher_v2/tests/test_ci_security_gates.py`, `publisher_v2/tests/test_pip_audit_ignore.py` |
| Deps | `pyproject.toml`, `uv.lock` (via `uv sync`) | — |
| Docs | `SECURITY.md` | — |

### Non-negotiables for this item

- [ ] Preview mode: N/A — no `publisher_v2` runtime code touched; this item is entirely CI/CD
  tooling and repo config.
- [ ] Secrets: do not add, invent, or log `GITGUARDIAN_API_KEY` or any other secret value; the
  presence-guard must degrade to a clean skip when the secret is absent, which it is today.
- [ ] Auth: N/A — no web endpoint changes.
- [ ] Async hygiene: N/A — no async code touched.
- [ ] Coverage: `scripts/pip_audit_ignore.py` is new source under test — ensure
  `test_pip_audit_ignore.py` exercises both the valid-entries path and every `ValueError` branch
  (missing `id`/`reason`/`expires`, expired entry) so it doesn't drag down the ≥85% overall gate.
  Confirm with the actual coverage tool whether `scripts/` is in-scope for the gate (per
  `pyproject.toml [tool.coverage.run] source`, currently `publisher_v2/src/publisher_v2` only) —
  if `scripts/` is excluded from the coverage source, this module's own tests still matter for
  correctness even though they won't move the percentage.
- [ ] Backward compatibility: none of the CLI flags, web endpoints, or config semantics this
  repo ships to users are touched. `uv run pytest`/`ruff`/`mypy` invocations from `AGENTS.md`/
  `CLAUDE.md` are unaffected.

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-055_ci-security-gates.md
```
