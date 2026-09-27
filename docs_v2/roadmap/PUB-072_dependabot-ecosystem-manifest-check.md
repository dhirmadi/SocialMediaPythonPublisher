# PUB-072: Assert Every Declared Dependabot Ecosystem Has a Manifest It Can Read

| Field | Value |
|-------|-------|
| **ID** | PUB-072 |
| **Category** | Ops |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Proposal |
| **Dependencies** | PUB-055, PUB-066 |

## User Story

As a maintainer, I want CI to fail when `.github/dependabot.yml` declares an ecosystem that has no
manifest it can parse at its `directory`, so that a config which cannot possibly run is caught in
review instead of by reading Dependabot's job logs weeks later.

## Problem

PUB-055 added `.github/dependabot.yml` with `pip`, `uv` and `github-actions` entries and a test,
`test_dependabot_config_groups_weekly_pip_and_actions_updates`, asserting the `pip` entry is
**present**. Both Python updaters then aborted on their first run. PUB-066 removed the dangling
`-r requirements.txt` that caused the abort.

Neither item closed the underlying gap: **nothing asserts a declared ecosystem has a manifest it can
actually read.** PUB-055's test checks the config's shape; PUB-066's tests check requirements-file
hygiene. The suite is fully green in exactly the state where Dependabot errors — which is how
PUB-055 shipped a config that could not run, and the state the repository is still in for `pip`:

- `/` contains `pyproject.toml` (PEP 621 `[project].dependencies` + PEP 735 `[dependency-groups]`)
  and `uv.lock`. Nothing else Python.
- The `pip` ecosystem reads `requirements*.txt`, `setup.py`, `setup.cfg`, Pipfile and poetry's
  `[tool.poetry]` table. None exist here, and PEP 735 dependency groups are not a pip manifest.
- `.github/dependabot.yml:9-11` already concedes the `pip` entry "cannot read `uv.lock`" and "bumps
  nothing on its own".

So a green suite currently coexists with a `pip` entry that has nothing to act on.

## Desired Outcome

A test fails if any ecosystem declared in `.github/dependabot.yml` has no manifest of a type that
ecosystem supports at its declared `directory`, and the `pip` entry's fate is settled rather than
left as a known-inert declaration.

## Scope

**In scope:**
- A manifest-per-ecosystem test over `.github/dependabot.yml` with an explicit, documented mapping
  of ecosystem → accepted manifest filenames, covering at least the three declared ecosystems.
- A decision on the `pip` entry: keep it (only if a manifest it reads is deliberately committed) or
  drop it. Dropping it amends PUB-055's AC5 and
  `test_dependabot_config_groups_weekly_pip_and_actions_updates`, so that is a spec amendment, not
  a config tweak.
- If `pip` is dropped, record in `.github/dependabot.yml` why `uv` alone is the Python updater.

**Out of scope:**
- Validating the config against GitHub's own schema (GitHub accepts it; the problem is semantic).
- Calling any GitHub API from the test. It must work offline against tracked files.
- Re-litigating PUB-066's requirements-file hygiene tests.

## Acceptance Criteria

- AC1: Given `.github/dependabot.yml`, when
  `publisher_v2/tests/test_dependabot_config.py::test_every_declared_ecosystem_has_a_manifest_it_can_read`
  runs, then every `package-ecosystem` entry resolves to at least one tracked manifest of a type
  that ecosystem supports, at that entry's `directory`.
- AC2: Given an ecosystem whose manifests are all absent, when that test runs, then it fails naming
  the ecosystem, its `directory`, and the manifest filenames it looked for.
- AC3: Given the ecosystem → manifest mapping, when a reader opens the test, then each ecosystem's
  accepted filenames carry a comment citing why those and not others (the `pip` row must state that
  PEP 735 `[dependency-groups]` is not a pip manifest).
- AC4: Given the `pip` decision, when the item closes, then either the entry is removed and
  PUB-055's AC5 and its test are amended in the same change, or a manifest `pip` reads is tracked at
  `/` and the test passes because of it — not because the mapping was widened to accept
  `pyproject.toml` for `pip`.

## Implementation Notes

The existing Dependabot test from PUB-055 shows how to parse the config; extend that module or add a
sibling. Enumerate tracked files with `git ls-files` semantics as
`publisher_v2/tests/test_requirements_files.py` (PUB-066) does, so an untracked local export cannot
make the test pass.

AC4 is the honest crux: the cheap way to green this test is to declare `pyproject.toml` a valid
`pip` manifest. That would restore precisely the false confidence this item exists to remove.

## Risks

- **A wrong mapping fails open.** If the accepted-filenames list is too generous the test passes
  while Dependabot still cannot read anything — the PUB-055 failure mode repeated one level up.
  Mitigate by mutation-checking: remove each manifest in turn and confirm the test goes red.
- Dependabot's supported-manifest list changes over time, so the mapping will drift. It is still
  worth more than no check; note the drift risk in the test's docstring.

## Success Metrics

- Every ecosystem in `.github/dependabot.yml` either completes a run or is not declared.

## Related

- PUB-055 (#236) introduced the config and the presence-only test; PUB-066 (#245) removed the
  dangling `-r` and documented this gap as the root fix it did not perform.
- Parent tracker [#243](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/243)
