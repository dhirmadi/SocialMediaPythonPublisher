# PUB-079: Dependabot Correctness and Scope Batch — Manifest Check, Requirements-Guard Gaps, Live-Tree Scoping, `uv` Resolution

| Field | Value |
|-------|-------|
| **ID** | PUB-079 |
| **Category** | Ops |
| **Priority** | P1 |
| **Effort** | M |
| **Status** | Proposal |
| **Dependencies** | PUB-055, PUB-066 (both merged) |
| **Supersedes** | PUB-072, PUB-073, PUB-075, PUB-076 |

## User Story

As a maintainer, I want Dependabot's config to be provably readable, its requirements-guard to catch
the reference patterns it currently waves through, its PR queue scoped to dependencies we actually
maintain, and its `uv` resolution to complete without error, so that the PR queue is signal — including
security patches like `pydantic` — rather than noise I have to re-close every week.

## Problem

PUB-066 unblocked the Python updaters. Its first live run (2026-09-27) proved the pipeline works end
to end, and in doing so surfaced four related, still-open defects, all touching the same
`.github/dependabot.yml` / `test_ci_security_gates.py` / `test_requirements_files.py` surface:

**1. No test notices whether a declared ecosystem can read anything at all.** PUB-055 added
`test_dependabot_config_groups_weekly_pip_and_actions_updates`, which asserts the `pip` entry is
*present* — shape only. Between PUB-055 and PUB-066, the suite was fully green while both Python
updaters were aborting on every run. PUB-066 itself is the sharpest illustration: it deleted
`requirements-dev.txt` — at the time the only `requirements*.txt` in the tree — and the suite did not
blink, because `pyproject.toml` remains and `pip` reads PEP 621. Nothing checked that; nothing would
have complained had `pyproject.toml` been the file that went. (An earlier draft of this item's
manifest-availability sub-problem was drafted on the wrong premise — that `pip` had no manifest it
could read. GitHub's docs and PUB-066's live run both confirm PEP 621 `pyproject.toml` is read; the
premise is corrected here.)

**2. The requirements-guard has two known blind spots.** PUB-066's guard (`REQUIREMENT_FLAG`,
`_is_requirements_name` in `test_requirements_files.py`) matches only `-r`/`--requirement`, so a
dangling `-c missing.txt` reproduces the exact `dependency_file_not_found` abort PUB-066 fixed, and
the guard stays green. Separately, the target capture (`[^\s#]+`) is defeated by trailing punctuation
— `-r requirements.txt.` or `-r requirements.txt)` inside a fenced code block yields a captured name
that no longer matches `*requirements*.txt`, and the line is silently skipped. (Unfenced prose is
already excluded by design via `_code_lines`, so this only widens matching within fenced content —
it must not start flagging prose.)

**3. The first successful run opened five unmergeable or duplicate PRs.** `code_v1/requirements.txt`
is tracked and both Python ecosystems read it, so `configparser` and `replicate` — V1-only
dependencies referenced nowhere in `pyproject.toml` — produced PRs #254, #256 and #260 against an
archived tree `CLAUDE.md` says must never be edited. Separately, `pyproject.toml` deliberately caps
`instagrapi<3` (3.x swaps the HTTP transport and breaks session persistence in ways this repo's mocked
tests cannot verify); without an `ignore` rule, #255 and #258 tried to lift that cap and will return
every week. `pip` and `uv` also proposed the same `configparser` and `instagrapi` bumps independently
(#256/#260 byte-identical) — `pip`'s only observed contribution so far is duplicates plus the
`code_v1/` noise, so its fate needs a decision, not indefinite deferral.

**4. The `uv` updater cannot resolve a `pydantic` bump at all.** `instagrapi==2.6.9` pins
`pydantic==2.13.4` exactly, so any `pydantic` bump is unsatisfiable while the deliberate
`instagrapi>=2.6.9,<3` cap holds — a real conflict between two decisions, not a mistake. Separately,
`requires-python = ">=3.12,<4.0"` forces uv to resolve splits this repo never ships (the failing case
was `python_full_version >= '3.14' and sys_platform == 'android'`); uv's own hint points at narrowing
it. Net effect: `pydantic` security patches cannot reach a PR via `uv` today.

## Desired Outcome

A test fails if any declared Dependabot ecosystem has no manifest of a type it supports at its
`directory`. The requirements-guard catches a dangling `-c`/`--constraint` reference and matches a
punctuation-trailed filename inside fenced content, with no new false positive on prose that quotes
an old command. Dependabot opens no PR against `code_v1/` and none that lifts the `instagrapi` major
cap, while still updating everything in the live tree; the `pip` entry's fate is decided, not left
open. The `uv` updater completes without a resolution error, and a `pydantic` advisory can reach a PR.

## Scope

**In scope:**
- One manifest-per-ecosystem test over `.github/dependabot.yml`, with an explicit ecosystem →
  accepted-manifest-filenames mapping, each row carrying a dated citation of GitHub's supported-
  manifests documentation (the `pip` row recording that PEP 621 `pyproject.toml` is accepted and that
  PEP 735 `[dependency-groups]` support is unresolved per
  [dependabot-core#10847](https://github.com/dependabot/dependabot-core/issues/10847)).
- Widen `REQUIREMENT_FLAG` to `-c`/`--constraint` (and the `-cfile`/`--constraint=file` spellings
  already handled for `-r`); strip trailing punctuation that cannot be part of a filename (`.`, `,`,
  `)`, `` ` ``, `'`, `"`, `;`, `:`, without stripping past a filename's own `.txt`) from the captured
  target; add fixture tests pinning both directions (a fenced dangling reference with trailing
  punctuation must fail; a fenced line quoting the old command for a file that exists must not).
- Confine both Python ecosystems to the live tree (`exclude-paths` for `code_v1/`, or a per-dependency
  `ignore` fallback if `exclude-paths` proves not to apply to the `pip`/`uv` scanners — verify by an
  actual run, not by reading the option reference); an `ignore` rule for `instagrapi` major bumps
  (`update-types: ["version-update:semver-major"]`) with a comment pointing at `pyproject.toml`'s cap;
  close the five PRs from Problem §3 unmerged, noting why; decide the `pip` entry's fate (drop as
  duplicative of `uv`, amending PUB-055's AC5 and its groups-test in the same change — or keep, with a
  comment naming what it covers that `uv` does not).
- Narrow `requires-python` to match what CI and `[tool.ruff] target-version` actually test
  (`>=3.12,<3.13`); decide and record the `pydantic` pin relative to `instagrapi`'s exact requirement,
  with a comment stating that relaxing it depends on the `instagrapi` major (the same convention the
  existing `instagrapi` cap comment uses).
- Extend the Dependabot config test to assert the `code_v1/` exclusion and the `instagrapi` `ignore`
  rule are present, so removing either fails CI.
- Mutation-check every new guard test per PUB-074 (already merged): show the test red before the fix,
  green after — reading the matcher is not evidence, and this exact class of guard (a test asserting
  an absence) is the one PUB-066 shipped two vacuous instances of.

**Out of scope:**
- Full CommonMark parsing for the requirements-guard; scanning unfenced prose for install
  instructions (excluded by design); `pip`'s other flags (`-e`, `--find-links`, `--index-url`).
- Deleting `code_v1/requirements.txt` — the archived tree stays as-is; scoping the updater is the fix.
- Lifting the `instagrapi<3` cap — its own piece of work, per `pyproject.toml`'s comment.
- Validating `.github/dependabot.yml` against GitHub's schema (GitHub already accepts it; the failure
  mode here is semantic) or any network/API call from the manifest-availability test.
- Dropping `instagrapi` or replacing the Instagram publisher (PUB-056 territory).

## Acceptance Criteria

- AC1: Given `.github/dependabot.yml`, when
  `test_ci_security_gates.py::test_every_declared_ecosystem_has_a_manifest_it_can_read` runs, then
  every `package-ecosystem` entry resolves to at least one tracked manifest of a type that ecosystem
  supports, at that entry's `directory`; it fails naming the ecosystem, directory and filenames looked
  for when none resolve.
- AC2: Given each manifest at `/` is removed in turn, then the test in AC1 goes red for the ecosystem
  that lost its last readable manifest (mutation-proof, per PUB-074).
- AC3: Given a tracked requirements file containing `-c missing.txt`, `--constraint missing.txt`,
  `-cmissing.txt` or `--constraint=missing.txt`, when
  `test_no_requirements_file_references_a_missing_target` runs, then it fails naming the file, line
  and target.
- AC4: Given a tracked, fenced `-r requirements.txt.` or `-r requirements.txt)` where that file is
  absent, when the same test runs, then it fails, having matched the target on its real filename.
- AC5: Given the punctuation-stripping change, when
  `test_the_docs_do_not_recommend_a_missing_requirements_file` runs against tracked docs that cite
  `pip install -r requirements-dev.txt` in prose backticks, then it still passes, and a fixture test
  asserts the same command inside a fence for an absent file does fail.
- AC6: Given `.github/dependabot.yml`, when
  `test_ci_security_gates.py::test_dependabot_excludes_the_archived_v1_tree` runs, then it asserts the
  config scopes the Python ecosystems away from `code_v1/`.
- AC7: Given `.github/dependabot.yml`, when
  `test_ci_security_gates.py::test_dependabot_ignores_instagrapi_major_bumps` runs, then it asserts an
  `ignore` entry for `instagrapi` covering `version-update:semver-major`, with a comment citing
  `pyproject.toml`'s `<3` cap.
- AC8: Given the `pip` entry, when this item closes, then it is either removed (with PUB-055's AC5 and
  its groups-test amended in the same change, reason recorded as redundancy with `uv`) or kept with a
  comment naming what it covers that `uv` does not.
- AC9: **Live verification.** Given the change merged, when Dependabot next runs (touch
  `dependabot.yml` to force it), then no new PR targets `code_v1/`, none proposes `instagrapi` 3.x, and
  no two PRs propose the same bump. Link the run.
- AC10: Given the five PRs from Problem §3, when this item closes, then each is closed unmerged with a
  one-line reason (or, if the config was still unscoped when Dependabot re-ran, their re-opened
  equivalents are too).
- AC11: Given `pyproject.toml`, when
  `test_packaging_metadata.py::test_requires_python_matches_the_tested_interpreter` runs, then
  `requires-python`'s ceiling matches the Python version CI and `[tool.ruff] target-version` use.
- AC12: Given the `pydantic` constraint, when a reader opens `pyproject.toml`, then a comment records
  that `instagrapi` pins `pydantic` exactly, names the version, and states that relaxing it requires
  the `instagrapi` major.
- AC13: **Live verification.** Given the change merged, when the `uv` updater next runs (touch
  `dependabot.yml` to force it), then it completes without `dependency_file_not_resolvable`. Link the
  run.
- AC14: Given the change, when `uv lock` and the full test suite run locally, then the lockfile
  resolves and all tests pass on Python 3.12 — narrowing `requires-python` must not alter the
  installed set.

## Implementation Notes

- All four constituent changes read or write `.github/dependabot.yml` and/or
  `test_ci_security_gates.py`; land them as separate, small PRs in whatever order is convenient, but
  expect to rebase across them rather than parallelizing blind — that file collision is exactly why
  this item exists as one tracked spec instead of four.
- `test_ci_security_gates.py:185`'s `test_dependabot_config_groups_weekly_pip_and_actions_updates`
  already shows how this repo parses the config; extend it rather than starting a new module. Enumerate
  tracked files with `git ls-files` semantics (as `test_requirements_files.py` does) so an untracked
  local export cannot make AC1 pass.
- `REQUIREMENT_FLAG` and `_is_requirements_name` are adjacent in `test_requirements_files.py`; the
  whole AC3-AC5 change is in that file plus a wording amendment in `PUB-066_dependabot-python-updaters.md`
  (archived) naming constraints files.
- `uv lock --upgrade --dry-run` reproduces the `pydantic`/`requires-python` resolution locally without
  touching the lockfile — the fast way to test a candidate `requires-python` for AC11/AC13.
- AC2's and every other mutation-proof requirement here exist because PUB-066's first review passed a
  matcher that was partly vacuous (a git pathspec wider than its basename filter) — found only by
  reintroducing the defect. Do not skip it.

## Risks

- **A wrong manifest mapping fails open in either direction.** Too generous and AC1 passes while
  Dependabot can read nothing; too strict and it fails on a manifest Dependabot handles fine (the
  mistake this item's own `pip`-premise correction fixes). AC1's dated citations and AC2's mutation
  proof are the mitigations.
- **Over-eager punctuation stripping invents filenames.** Keep the strip list closed and explicit.
- **Over-broad `code_v1/` exclusion could silence the live tree.** AC9's live run plus continued
  legitimate PRs arriving is the check.
- An `instagrapi` major `ignore` rule is a standing decision that hides real advisories for that
  dependency's majors; it is scoped to majors only, so 2.x security patches still arrive.
- **A too-narrow `requires-python` ceiling blocks the next Python upgrade** — `<3.13` makes moving to
  3.13 an explicit, deliberate change. That is the point (AC11 ties it to what is actually tested), but
  record it as a trade, not an accident.
- Pinning `pydantic` to `instagrapi`'s exact requirement means a `pydantic` advisory cannot be patched
  without moving `instagrapi` first — that coupling already exists in the lockfile; AC12 makes it
  visible instead of surprising.

## Success Metrics

- Removing the last manifest an ecosystem can read fails CI instead of quietly disabling that updater.
- No requirements-file reference class remains that the guard skips silently.
- Zero Dependabot PRs against `code_v1/` or `instagrapi` 3.x over the following month, with legitimate
  live-tree PRs still arriving.
- The `uv` updater reports no errors on its next scheduled run.

## Related

- PUB-055 (#236) introduced `.github/dependabot.yml` and its presence-only test.
- PUB-066 (#245, #253) unblocked the Python updaters and is the worked example behind every defect in
  this item.
- PUB-074 is the mutation-proof requirement AC2 and the other guard-test ACs invoke.
- Supersedes [PUB-072](archive/PUB-072_dependabot-ecosystem-manifest-check.md),
  [PUB-073](archive/PUB-073_requirements-guard-completeness.md),
  [PUB-075](archive/PUB-075_dependabot-scope-to-live-tree.md),
  [PUB-076](archive/PUB-076_uv-resolution-instagrapi-pydantic.md) — all four surfaced from the same PUB-066
  live run, touch the same `dependabot.yml`/`test_ci_security_gates.py` surface, and were already
  cross-referencing each other's scope decisions (PUB-072's `pip` question moved to PUB-075; PUB-073
  and PUB-072 both cite the same file). Batched here so a maintainer resolves the whole Dependabot
  surface in one pass. No scope was added or removed in the merge; every AC above traces to an AC in
  one of the four originals.

## Change Log

- 2026-09-27 — Created by merging PUB-072, PUB-073, PUB-075 and PUB-076 at the user's request to
  reduce the number of separately-tracked security roadmap items (12 → fewer, grouped by shared
  file/tooling).
