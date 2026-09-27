# PUB-076: The `uv` Updater Cannot Resolve — `instagrapi` Pins `pydantic` Exactly

| Field | Value |
|-------|-------|
| **ID** | PUB-076 |
| **Category** | Ops |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Proposal |
| **Dependencies** | PUB-066 |

## User Story

As a maintainer, I want the `uv` updater to finish without error, so that lockfile updates — including
security patches — are not blocked by an unsatisfiable resolution.

## Problem

PUB-066 got both Python updaters past file fetching. The `uv` job now fails one stage later
([run 36314786947](https://github.com/dhirmadi/SocialMediaPythonPublisher/actions/runs/36314786947),
2026-09-27) with `dependency_file_not_resolvable` while trying to bump `pydantic`:

```
error: No solution found when resolving dependencies for split
  (markers: python_full_version >= '3.14' and python_full_version < '4.0' and sys_platform == 'android')
  cause: Because instagrapi>=2.6.10,<=2.18.20 depends on pydantic{sys_platform == 'android'}==2.12.5
         and pydantic{sys_platform == 'android'}==2.13.5, we can conclude that
         instagrapi>=2.6.10,<=2.18.20 cannot be used.
         And because instagrapi==2.6.9 depends on pydantic==2.13.4, we can conclude that
         instagrapi>=2.6.9,<=2.18.20 depends on pydantic==2.13.4.
         And because your project depends on instagrapi>=2.6.9,<3 and pydantic==2.13.5,
         we can conclude that your project's requirements are unsatisfiable.

hint: While the active Python version is 3.12, the resolution failed for other Python versions
supported by your project. Consider limiting your project's supported Python versions using
`requires-python`.
```

Two independent causes combine:

1. **`instagrapi` pins `pydantic` exactly.** `instagrapi==2.6.9` requires `pydantic==2.13.4`, so any
   `pydantic` bump Dependabot proposes is unsatisfiable while the `instagrapi>=2.6.9,<3` cap holds.
   The cap is deliberate (3.x swaps the HTTP transport to curl-cffi), so this is a real conflict
   between two decisions, not a mistake.
2. **`requires-python = ">=3.12,<4.0"` makes uv resolve splits we do not ship.** The failing split is
   `python_full_version >= '3.14' and sys_platform == 'android'`. This repo deploys on Python 3.12 to
   Heroku; Android is not a target. The open upper bound forces uv to satisfy platforms nobody uses,
   and uv's own hint points at narrowing it.

The job's other work still succeeded — [#257](https://github.com/dhirmadi/SocialMediaPythonPublisher/pull/257)
grouped 10 updates — so this is one blocked dependency, not a dead updater. It does mean `pydantic`
security patches will not arrive by this route.

## Desired Outcome

The `uv` updater completes without a resolution error, and a `pydantic` advisory can reach a PR.

## Scope

**In scope:**
- Decide and apply the `requires-python` narrowing. `>=3.12,<3.13` matches what is actually deployed
  and tested (`target py312`, CI on 3.12) and removes the 3.14/android splits.
- Decide what to do about the `pydantic` pin: most likely pin `pydantic` to what `instagrapi` requires
  and record the coupling, so Dependabot stops proposing an impossible bump, with a note that lifting
  it depends on the `instagrapi` major.
- Verify by a live `uv` run that the error is gone.

**Out of scope:**
- Lifting the `instagrapi<3` cap (its own work, per `pyproject.toml`'s comment).
- Dropping `instagrapi` or replacing the Instagram publisher — PUB-056 territory.
- The `pip` ecosystem, which succeeds today.

## Acceptance Criteria

- AC1: Given `pyproject.toml`, when
  `publisher_v2/tests/test_packaging_metadata.py::test_requires_python_matches_the_tested_interpreter`
  runs, then `requires-python`'s ceiling matches the Python version CI and `[tool.ruff] target-version`
  use, so the two cannot drift.
- AC2: Given the `pydantic` constraint, when a reader opens `pyproject.toml`, then a comment records
  that `instagrapi` pins `pydantic` exactly, names the version, and states that relaxing it requires
  the `instagrapi` major — the same convention the existing `instagrapi` cap comment uses.
- AC3: **Live verification.** Given the change merged, when the `uv` updater next runs (touch
  `dependabot.yml` to force it), then it completes without `dependency_file_not_resolvable`. Link the run.
- AC4: Given the change, when `uv lock` and the full test suite run locally, then the lockfile resolves
  and all tests pass on Python 3.12 — narrowing `requires-python` must not alter the installed set.

## Implementation Notes

`uv lock --upgrade --dry-run` reproduces the resolution locally without touching the lockfile, which is
the fast way to test a candidate `requires-python`.

Narrowing `requires-python` is a published-metadata change. This package is not distributed on PyPI
(it is an application, `version = "0.1.0"`), so the blast radius is local, but say so explicitly in the
commit rather than leaving it implied.

## Risks

- **A too-narrow ceiling blocks the next Python upgrade.** `<3.13` means moving to 3.13 becomes an
  explicit, deliberate change. That is arguably the point — AC1 ties it to what is actually tested —
  but it is a trade, and the item should record the choice rather than treat it as obvious.
- Pinning `pydantic` to `instagrapi`'s exact requirement means a `pydantic` advisory cannot be patched
  without moving `instagrapi` first. That coupling already exists in the lockfile; AC2 makes it visible
  instead of surprising.

## Success Metrics

- The `uv` updater reports no errors on its next scheduled run.

## Related

- PUB-066 (#245, #253) unblocked file fetching and exposed this next layer.
- PUB-075 covers the other findings from the same first successful run.
