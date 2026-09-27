# PUB-072: Assert Every Declared Dependabot Ecosystem Has a Manifest It Can Read

| Field | Value |
|-------|-------|
| **ID** | PUB-072 |
| **Category** | Ops |
| **Priority** | P2 |
| **Effort** | XS |
| **Status** | Superseded |
| **Dependencies** | PUB-055, PUB-066 |
| **Archived date** | 2026-09-27 |

> **Superseded 2026-09-27.** Merged into [PUB-079: Dependabot Correctness and Scope Batch](../PUB-079_dependabot-correctness-and-scope-batch.md)
> along with PUB-073, PUB-075 and PUB-076 — all four surfaced from the same PUB-066 live run and touch
> the same `dependabot.yml`/`test_ci_security_gates.py` surface, batched to reduce the number of
> separately-tracked security roadmap items. No scope changed; see PUB-079 for the current AC set
> (AC1-AC2 there trace to this item's AC1-AC4, corrected premise included).

> **Rescoped 2026-09-27.** This item was drafted on a wrong premise — that Dependabot's `pip`
> ecosystem had no manifest it could read here — and with a second job, deciding whether the `pip`
> entry should exist at all. Both are settled or moved:
>
> - **The premise was wrong.** GitHub's supported-ecosystems reference states (checked 2026-09-27):
>   "Dependabot supports updates to `pyproject.toml` files if they follow the PEP 621 standard." This
>   repo's `pyproject.toml` is PEP 621. PUB-066's live run then confirmed it — the `pip` job
>   [succeeded](https://github.com/dhirmadi/SocialMediaPythonPublisher/actions/runs/36314787005).
> - **The keep-or-drop-`pip` decision moved to PUB-075**, which owns `.github/dependabot.yml` scoping
>   and has the duplicate-PR evidence in hand.
>
> What remains is one narrow, still-unbuilt thing: the test below. Read the Problem accordingly.

## User Story

As a maintainer, I want CI to fail when `.github/dependabot.yml` declares an ecosystem with no
manifest it can read at its `directory`, so that a config which cannot run is caught in review rather
than by reading updater logs weeks later.

## Problem

Two items have now touched this config and neither closed the gap:

- PUB-055 added `.github/dependabot.yml` plus `test_dependabot_config_groups_weekly_pip_and_actions_updates`,
  which asserts the `pip` entry is **present**. Shape only.
- PUB-066 fixed the dangling `-r requirements.txt` that made both Python updaters abort. Its tests
  assert requirements-file hygiene.

Between them, the suite was fully green while both Python updaters were aborting on every run. That is
the gap: **no test notices whether a declared ecosystem can read anything at all.**

The sharpest illustration is PUB-066 itself. It deleted `requirements-dev.txt` — at the time the only
`requirements*.txt` in the tree — and the suite did not blink. That happened to be safe, because
`pyproject.toml` remains and `pip` reads PEP 621. But nothing checked it, and nothing would have
complained had `pyproject.toml` been the file that went.

Current state of `/`, for the record: `pyproject.toml` (PEP 621 `[project].dependencies` plus PEP 735
`[dependency-groups]`) and `uv.lock`. No `requirements*.txt`, `setup.py`, `setup.cfg`, Pipfile or
poetry `[tool.poetry]` table.

## Desired Outcome

A test fails if any ecosystem declared in `.github/dependabot.yml` has no manifest of a type that
ecosystem supports at its declared `directory`.

## Scope

**In scope:**
- One manifest-per-ecosystem test over `.github/dependabot.yml`, with an explicit ecosystem →
  accepted-manifest-filenames mapping covering the declared ecosystems.
- A dated citation per mapping row, so the next reader can tell when it was last checked against
  GitHub's docs rather than inferred.

**Out of scope:**
- Whether the `pip` entry earns its place, and every other `.github/dependabot.yml` scoping question
  (`exclude-paths`, `ignore` rules) — **PUB-075** owns the config's contents.
- Validating the config against GitHub's schema. GitHub accepts it; the failure mode here is semantic.
- Any network or API call from the test. It must work offline against tracked files.
- Re-litigating PUB-066's requirements-file hygiene tests.

## Acceptance Criteria

- AC1: Given `.github/dependabot.yml`, when
  `publisher_v2/tests/test_ci_security_gates.py::test_every_declared_ecosystem_has_a_manifest_it_can_read`
  runs, then every `package-ecosystem` entry resolves to at least one tracked manifest of a type that
  ecosystem supports, at that entry's `directory`.
- AC2: Given an ecosystem whose accepted manifests are all absent, when that test runs, then it fails
  naming the ecosystem, its `directory`, and the filenames it looked for.
- AC3: Given the mapping, when a reader opens the test, then each ecosystem's accepted filenames carry
  a comment citing GitHub's supported-manifests documentation and the date checked — the `pip` row
  recording that PEP 621 `pyproject.toml` is accepted, and that PEP 735 `[dependency-groups]` support
  is unresolved
  ([dependabot-core#10847](https://github.com/dependabot/dependabot-core/issues/10847)).
- AC4: Given the test, when each manifest at `/` is removed in turn, then the test goes red for the
  ecosystem that lost its last readable manifest. Record the mutation results per PUB-074 — a test
  asserting an absence is exactly the kind that passes while asserting nothing.

## Implementation Notes

`publisher_v2/tests/test_ci_security_gates.py` already parses this config (see
`test_dependabot_config_groups_weekly_pip_and_actions_updates` at `:185`); add the test there rather
than starting a new module. Enumerate tracked files with `git ls-files` semantics, as
`publisher_v2/tests/test_requirements_files.py` (PUB-066) does, so an untracked local export cannot
make the test pass.

AC4 is not optional ceremony. This item's whole value is a guard, and PUB-066 shipped two guards that
could not fail — one because a git pathspec was wider than its basename filter, one because a fence
toggle inverted silently. Prove this one fails.

## Risks

- **A wrong mapping fails open in either direction.** Too generous and the test passes while
  Dependabot can read nothing — the PUB-055 failure mode one level up. Too strict and it fails on a
  manifest Dependabot handles fine, which is the mistake this item's own first draft made about PEP
  621 `pyproject.toml`. AC3's dated citations and AC4's mutations are the mitigations.
- Dependabot's supported-manifest list changes over time, so the mapping will drift. A dated,
  cited mapping that occasionally lags still beats no check; say so in the test's docstring.

## Success Metrics

- Removing the last manifest an ecosystem can read fails CI instead of quietly disabling that updater.

## Related

- PUB-055 (#236) introduced the config and the presence-only test.
- PUB-066 (#245, #253) fixed the abort and is the worked example of the gap this item closes.
- PUB-075 owns what `.github/dependabot.yml` declares and excludes, including the `pip` entry's fate.
- PUB-074 is the mutation-proof requirement AC4 invokes.
