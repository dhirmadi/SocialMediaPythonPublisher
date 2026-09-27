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
hygiene. Between them, the suite was fully green in the state where both Python updaters aborted.

What `/` actually contains after PUB-066: `pyproject.toml` (PEP 621 `[project].dependencies` plus
PEP 735 `[dependency-groups]`) and `uv.lock`. Nothing else Python — no `requirements*.txt`,
`setup.py`, `setup.cfg`, Pipfile, or poetry `[tool.poetry]` table.

**The `pip` entry is therefore readable, not inert.** GitHub's supported-ecosystems reference states
(checked 2026-09-27): "Dependabot supports updates to `pyproject.toml` files if they follow the PEP
621 standard." This repo's `pyproject.toml` is PEP 621, so `pip` has a manifest at `/`. An earlier
draft of this item asserted the opposite; that was wrong and is corrected here. PEP 735
`[dependency-groups]` support is a separate question
([dependabot-core#10847](https://github.com/dependabot/dependabot-core/issues/10847)) and this item
should not assume either answer.

So the gap is narrower but real: **no test would notice if a declared ecosystem lost its last
readable manifest.** PUB-066 removed the only `pip` manifest in the tree (`requirements-dev.txt`)
and the suite did not blink — it happened to be safe because `pyproject.toml` remains, but nothing
checked that.

**The first successful run settles the redundancy question empirically (2026-09-27).** With both
entries live, the two ecosystems proposed the same bumps twice:

| Dependency | `pip` PR | `uv` PR |
|------------|----------|---------|
| `configparser` (in `code_v1/`) | [#256](https://github.com/dhirmadi/SocialMediaPythonPublisher/pull/256) | [#260](https://github.com/dhirmadi/SocialMediaPythonPublisher/pull/260) |
| `instagrapi` | [#255](https://github.com/dhirmadi/SocialMediaPythonPublisher/pull/255) (widen to `<4`) | [#258](https://github.com/dhirmadi/SocialMediaPythonPublisher/pull/258) (3.0.13) |

#256 and #260 are byte-identical proposals. So the `pip` entry is not inert — it is *duplicative*, and
it also generates the `code_v1/` noise PUB-075 addresses. That is the concrete case for dropping it,
and it is evidence rather than argument.

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
  accepted filenames carry a comment citing why those and not others — the `pip` row recording that
  PEP 621 `pyproject.toml` is accepted, with the supported-manifests citation and the date checked,
  and that PEP 735 `[dependency-groups]` support is unresolved
  ([dependabot-core#10847](https://github.com/dependabot/dependabot-core/issues/10847)).
- AC4: Given the `pip` decision, when the item closes, then the reason recorded is **redundancy with
  the `uv` entry**, not unreadability — and whichever way it goes, the mapping's `pip` row accepts
  PEP 621 `pyproject.toml` because GitHub documents that it does, with the citation in the test. If
  the entry is dropped, PUB-055's AC5 and
  `test_dependabot_config_groups_weekly_pip_and_actions_updates` are amended in the same change. If
  it is kept, the item records what `pip` adds that `uv` does not, since `.github/dependabot.yml:10-12`
  claims it "bumps nothing on its own".

## Implementation Notes

The existing Dependabot test from PUB-055 shows how to parse the config; extend that module or add a
sibling. Enumerate tracked files with `git ls-files` semantics as
`publisher_v2/tests/test_requirements_files.py` (PUB-066) does, so an untracked local export cannot
make the test pass.

AC4 is the honest crux, and it cuts the other way from an earlier draft of this item: declaring
`pyproject.toml` a valid `pip` manifest is *correct*, because GitHub documents that support. The
cheap fake-green to guard against is the opposite one — a mapping so permissive that any ecosystem
passes. Mutation-check it: remove each manifest in turn and confirm the test goes red (see PUB-074).

Also verify the `.github/dependabot.yml:10-12` comment while here. It says the `pip` ecosystem
"cannot read `uv.lock`" (true) "and every direct dependency in `pyproject.toml` is a bare `>=` lower
bound, so it bumps nothing on its own" — that second clause only makes sense if `pip` reads
`pyproject.toml`, which it does. The comment and the entry's justification should be made consistent.

## Risks

- **A wrong mapping fails open in either direction.** Too generous and the test passes while
  Dependabot can read nothing (the PUB-055 failure mode one level up); too strict and it fails on a
  manifest Dependabot handles fine — the error an earlier draft of this item made about PEP 621
  `pyproject.toml`. Cite the supported-manifests doc per row, with the date checked.
  Mitigate by mutation-checking: remove each manifest in turn and confirm the test goes red.
- Dependabot's supported-manifest list changes over time, so the mapping will drift. It is still
  worth more than no check; note the drift risk in the test's docstring.

## Success Metrics

- Every ecosystem in `.github/dependabot.yml` either completes a run or is not declared.

## Related

- PUB-055 (#236) introduced the config and the presence-only test; PUB-066 (#245) removed the
  dangling `-r` and documented this gap as the root fix it did not perform.
- Parent tracker [#243](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/243)
