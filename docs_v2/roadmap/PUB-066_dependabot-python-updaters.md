# PUB-066: Unblock Dependabot's Python Updaters

| Field | Value |
|-------|-------|
| **ID** | PUB-066 |
| **Category** | Ops |
| **Priority** | P1 |
| **Effort** | XS |
| **Status** | Implementation Complete (AC3 pending live Dependabot run) |
| **Dependencies** | PUB-055 (merged, #236) |

## User Story

As a maintainer, I want Dependabot's `pip` and `uv` updaters to run, so that PUB-055's
success metric — an advisory reaching a Dependabot PR within a week — is actually
achievable for Python packages rather than only for GitHub Actions.

## Problem

PUB-055 added `.github/dependabot.yml`. On the first run after #236 merged, the
`github-actions` ecosystem worked and began opening PRs. Both Python ecosystems aborted:

```
updater | ERROR <job_1592916449> Error during file fetching; aborting: /requirements.txt not found
```

Runs: [pip 36262545153](https://github.com/dhirmadi/SocialMediaPythonPublisher/actions/runs/36262545153),
[uv 36262545796](https://github.com/dhirmadi/SocialMediaPythonPublisher/actions/runs/36262545796),
[github-actions 36262546123](https://github.com/dhirmadi/SocialMediaPythonPublisher/actions/runs/36262546123) (succeeded).

This also settles an open question from PUB-055: GitHub **does** accept `package-ecosystem: "uv"`
(the job definition reports `"package-manager":"uv"`), so the ecosystem name is valid. It simply
never reaches `pyproject.toml`/`uv.lock`.

### Root cause — a hypothesis, not yet proven

`requirements-dev.txt:5` contains `-r requirements.txt`, and **`requirements.txt` does not exist**
in the repository. It is a leftover from before the `uv` migration. The most likely explanation is
that both Python updaters scan `requirements*.txt` first, follow the dangling `-r`, and abort
before reading any other manifest.

**Evidence:** the error names exactly `/requirements.txt`; that path is referenced from exactly one
tracked file (`requirements-dev.txt:5`, confirmed by grep); and `github-actions`, which does not
scan requirements files, is the only ecosystem that succeeded.

**Not yet confirmed.** Dependabot's file-fetch behaviour is not observable from outside, so the fix
below must be validated by an actual updater run, not by reasoning. See Risks for the fallback if
the hypothesis is wrong.

A second, user-facing consequence of the same staleness: `.github/DEVELOPMENT.md:43` and
`CONTRIBUTING.md:136` both instruct contributors to `pip install -r requirements-dev.txt`, which
fails today for the same reason.

## Desired Outcome

Dependabot's `pip` and `uv` updaters complete without error, and no tracked requirements file
references a path that does not exist.

## Scope

**In scope:**
- Remove the stale `requirements-dev.txt`. It is hand-written, not the output of the
  `make export-reqs-dev` target that nominally generates it (a real export would contain pinned
  versions, not `-r`), and the target regenerates a valid one on demand.
- Fix `.github/DEVELOPMENT.md:43` and `CONTRIBUTING.md:136` to stop recommending it.
- A test asserting no tracked requirements file references a missing target, so this cannot recur.

**Out of scope:**
- Removing or restructuring the `make export-reqs` / `export-reqs-dev` targets; they are fine and
  are not what broke.
- Changing which ecosystems `.github/dependabot.yml` declares. AC5 of PUB-055 mandates the `pip`
  entry; whether to drop it is PUB-055's own follow-up, not this item's.
- Triaging the Dependabot PRs that appear once the updaters work.

## Acceptance Criteria

- AC1: Given the repository after this change, when
  `publisher_v2/tests/test_requirements_files.py::test_no_requirements_file_references_a_missing_target`
  runs, then it finds no `-r` / `--requirement` line in any tracked `requirements*.txt` pointing at
  a path that does not exist.
- AC2: Given the repository after this change, when
  `publisher_v2/tests/test_requirements_files.py::test_the_docs_do_not_recommend_a_missing_requirements_file`
  runs, then no tracked Markdown file instructs installing from a `requirements*.txt` that is absent.
- AC3: **Verification step, not a pytest AC.** Given this change merged to `main`, when Dependabot
  next runs, then the `pip` and `uv` jobs both complete without a `dependency_file_not_found` error.
  **Verification:** re-run from Insights → Dependency graph → Dependabot ("Check for updates"), or
  wait for the weekly schedule; link the successful run in the delivery PR. If they still fail, stop
  and apply the fallback in Risks rather than iterating blindly.

## Implementation Notes

`requirements-dev.txt` is tracked and its removal is the whole fix; keep the diff to that file, the
two docs, and the new test. Follow `test_coverage_gate_config.py` for reading repo-root files from a
test (`REPO_ROOT = Path(__file__).resolve().parents[2]`). Use `git ls-files` semantics — the test
should only consider tracked files, so an untracked local export does not fail the suite.

## Risks

- **The hypothesis may be wrong.** If Dependabot still reports `dependency_file_not_found` after the
  file is gone, the fallback is `exclude-paths` in `.github/dependabot.yml`, or dropping the `pip`
  entry and keeping only `uv`. The latter changes PUB-055's AC5 and
  `test_dependabot_config_groups_weekly_pip_and_actions_updates`, which asserts the `pip` ecosystem
  is present — so it is a spec amendment, not a config tweak.
- Deleting a tracked file could surprise someone whose local workflow installs from it. That workflow
  is already broken (the `-r` target is missing), so the deletion makes the breakage visible rather
  than causing it.

## Success Metrics

- A Dependabot PR for a Python dependency appears within one week of this merging — the metric
  PUB-055 claimed but could not deliver.

## Related

- Parent tracker [#243](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/243)
- PUB-055 (#236) introduced the Dependabot config; PUB-065 (#235) cleared the advisory backlog
