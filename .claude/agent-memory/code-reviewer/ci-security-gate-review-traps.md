---
name: ci-security-gate-review-traps
description: PUB-055 review traps — workflow-parsing tests that cannot detect gate deletion, uvx/--with pip-audit audit targets, composite actions whose pinned SHA still runs :latest, dependabot pip-vs-uv ecosystem
metadata:
  type: project
---

Traps found reviewing PUB-055 (CI security gates), worth re-checking whenever CI
security tooling, a workflow-parsing test, or a `scripts/*.py` CLI is touched.

**Why:** each of these looked correct in the diff and only failed under direct execution
or mutation.

**How to apply:**

- **A workflow-parsing test that only asserts negatives cannot detect gate deletion.**
  `test_ci_security_gates.py` asserts "no `|| true`", "no `continue-on-error`", "every
  `uses:` is a SHA" — 11 mutations survived it, including *deleting the whole pip-audit
  step*, `continue-on-error: ${{ true }}`, appending `exit 0` to the run block, swapping
  the audit target to `-r /dev/null`, unpinning `--with pip-audit`, a flow-style
  `- {uses: 'actions/checkout@v4'}` step, and dependabot `open-pull-requests-limit: 0` /
  `ignore: "*"` / `directory: "/nonexistent"`. Always demand at least one *positive*
  assertion that names the gate command and its target.
- `_is_truthy` handling of `"true"` does not cover `${{ ... }}`: any GitHub expression
  is an opaque string to `yaml.safe_load` and evaluates false in the test, true on the
  runner.
- Audit-target arithmetic here: `uvx pip-audit` = 29 pkgs (tool venv, vacuous);
  `uv run --with pip-audit pip-audit` = 113 (94 project + 19 of pip-audit's own tree,
  **including `pip` itself**); `uv export --frozen --no-emit-project --all-groups
  --no-hashes -o req.txt` + `pip-audit --no-deps -r req.txt` = 93, exactly the locked
  project set. The `-r` form works on macOS (no `ensurepip` crash) because `--no-deps`
  skips venv creation.
- **A SHA-pinned composite action can still run a mutable artifact.**
  `trufflesecurity/trufflehog`'s action.yml does `docker run "${IMAGE}:${VERSION}"` with
  `VERSION` defaulting to `latest`. Pinning the `uses:` SHA pins the wrapper, not the
  scanner; set `with: version: <x.y.z>`.
- Dependabot `package-ecosystem: "pip"` does **not** read `uv.lock` (that needs
  `"uv"`), and every direct dep here is a bare `>=` lower bound that any new release
  already satisfies — so the pip half of dependabot is inert for this repo.
- SHA-pin verification recipe (all 7 pins in PUB-055 verified correct):
  `gh api repos/X/git/ref/tags/vN -q .object.type+" "+.object.sha`, then deref annotated
  tags via `git/tags/<sha>`. `dependency-review-action`'s `v3` major tag derefs to
  `cc4f6536…` ("Release 3.1.5" merge) while the `v3.1.5` tag points at `c74b580d…`;
  both carry an identical `dist/index.js`, so that is a valid pin, not a mismatch.
- `scripts/pip_audit_ignore.py`: `[ignore]` (single table instead of `[[ignore]]`) →
  uncaught `AttributeError`, not the `ValueError` path; `id = true` → the literal id
  `"True"`; `id = false` → "missing a required `id`".
- Section placement is a correctness claim: the new pip-audit row landed under
  QUALITY_METRICS.md "6.2 Post-Merge Checks (Non-Blocking)" while the whole item is
  about making it pre-merge blocking.
