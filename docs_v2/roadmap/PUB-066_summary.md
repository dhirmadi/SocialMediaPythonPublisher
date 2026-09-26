# PUB-066 — Unblock Dependabot's Python Updaters: Implementation Summary

**Status:** Implementation Complete (AC3 pending live verification)
**Date:** 2026-09-26

## Files Changed

- `requirements-dev.txt` — **deleted**. Its `-r requirements.txt` pointed at a file that does not
  exist post-uv-migration; this dangling reference is the suspected cause of Dependabot's
  `Error during file fetching; aborting: /requirements.txt not found`.
- `.github/DEVELOPMENT.md` — install steps `pip install -r requirements.txt` /
  `pip install -r requirements-dev.txt` → `uv sync` / `uv sync --group dev`; two stale rows
  (`requirements.txt`, `requirements-dev.txt`) removed from the project-structure tree.
- `CONTRIBUTING.md` — same substitution; the `# If available` hedge dropped.
- `SECURITY.md` — "Applying Updates" snippet `pip install --upgrade -r requirements.txt` →
  `uv lock --upgrade && uv sync`.
- `publisher_v2/tests/test_requirements_files.py` — **new**, two hygiene tests (below).

Untouched by design: `Makefile` (`export-reqs` / `export-reqs-dev` still work), `README.md:132-133`
(describes those targets), `CHANGELOG.md:286` (history), `.github/dependabot.yml` (ecosystem set is
PUB-055's follow-up), `code_v1/`, `docs_v1/`.

## Acceptance Criteria

- [x] AC1 — no `-r` / `--requirement` line in any tracked `requirements*.txt` points at a missing
      path (test: `test_no_requirements_file_references_a_missing_target`)
- [x] AC2 — no tracked Markdown file instructs installing from an absent `requirements*.txt`
      (test: `test_the_docs_do_not_recommend_a_missing_requirements_file`)
- [ ] AC3 — **pending live verification.** Not a pytest AC. Requires a Dependabot `pip` + `uv` run
      after this merges to `main` (Insights → Dependency graph → Dependabot → "Check for updates");
      link the successful run in the delivery PR. If `dependency_file_not_found` persists, stop and
      apply the spec's Risks fallback (`exclude-paths`, or dropping the `pip` entry — the latter is
      a PUB-055 spec amendment, not a config tweak) rather than iterating.

Test names are verbatim from the handoff's Test-first targets table; no drift.

## Test Results

- Target file: 2 passed.
- Full suite: **1944 passed, 1 skipped** (random order, `--randomly-seed=2007871426` on the
  reviewer's independent run).

## Quality Gates

- Format: ✅ `259 files already formatted`
- Lint: ✅ `All checks passed!`
- Type check: ✅ `Success: no issues found in 65 source files`
- Tests: ✅ 1944 passed, 1 skipped, 0 failed
- Coverage: ✅ **93.37%** overall (7620 stmts / 505 missed), gate `fail_under = 85`. This item adds
  no `src/` coverage, as the handoff predicted.

All gates were re-run independently by `code-reviewer`, not carried over from the developer's report.

## Subagent Verdicts

- `code-reviewer`: **PASS WITH NITS** — no blockers; both new tests mutation-checked in a throwaway
  worktree and confirmed to fail when each defect is reintroduced (and to stay green for an
  *untracked* offending file, a commented-out `-r`, and `pip-audit -r`), so neither test is
  vacuously green. Nits recorded below.
- `security-auditor`: **N/A (not security-sensitive)** — no `publisher_v2/web/**`, auth,
  credential/config loading, secrets, preview-mode or async code touched. `SECURITY.md` prose did
  change, so the reviewer empirically verified the new command instead: `uv lock --upgrade
  --dry-run` emitted ~40 `Update`/`Add`/`Remove` lines (e.g. `ruff 0.15.2 -> 0.16.9`), confirming it
  genuinely re-resolves rather than silently no-opping in a security-remediation doc.

## Notes

### Documented deviations from the handoff's Order of work

1. **AC2 required five doc lines, not two.** The handoff names only
   `.github/DEVELOPMENT.md:43` and `CONTRIBUTING.md:136`. Read literally — and AC2 is written
   literally — three further lines instruct installing from the same missing root
   `requirements.txt`: `.github/DEVELOPMENT.md:42`, `CONTRIBUTING.md:133` and `SECURITY.md:230`.
   The AC2 test failed on exactly those three before the fix and cannot go green without them, so
   this was forced rather than discretionary. The spec's Implementation Notes ask to keep the diff
   to "that file, the two docs, and the new test"; `SECURITY.md` is a third doc, recorded here as
   the deviation. The spec's own Problem section already frames these as "a second, user-facing
   consequence of the same staleness". `code-reviewer` agreed on review.
2. **A second stale tree row was dropped.** No AC required removing
   `requirements.txt  # Production dependencies` from `.github/DEVELOPMENT.md`'s tree, but it
   documents a file that has not existed since the uv migration and sits adjacent to the row the
   handoff does mandate. Leaving it would be a knowingly false listing. `code-reviewer` agreed.

### Scope decision inside the AC2 test

`docs_v1/` and `code_v1/` are excluded from the AC2 scan. This is load-bearing, not cosmetic:
`docs_v1/DOCUMENTATION.md:1436` contains a fenced `pip install -r requirements.txt`, so without the
exclusion AC2 would be permanently red against an archived tree that `CLAUDE.md` forbids editing.
The exclusion is a prefix match on those two paths only and swallows no live path.

### Post-review fixes (applied)

- Hardened `test_requirements_files.py`: `_is_requirements_name` now matches the `*requirements*.txt`
  git pathspec instead of `requirements*.txt`, so a `dev-requirements.txt` with a dangling `-r` is no
  longer fetched and silently skipped (mutation-checked: it now goes red); both readers pass
  `encoding="utf-8"` (two tracked `.md` files are undecodable under a cp1252 locale); tracked files
  absent from the worktree are skipped instead of raising `FileNotFoundError`; and an out-of-tree
  target (`-r ../x.txt`) no longer crashes the failure message with `ValueError` from `relative_to`.
- `.github/DEVELOPMENT.md` / `CONTRIBUTING.md` setup blocks now use `uv venv` + `.venv` activation
  and a single `uv sync --group dev`. The previous `python -m venv venv` + `uv sync` pair left the
  activated `venv/` empty (uv installs into the project's `.venv`), so the next documented step,
  `pre-commit install`, would not find `pre-commit`.

### Open nits (not blocking, no action taken)

- `test_requirements_files.py` only scans ```-fenced blocks: an install line in unfenced prose, a
  4-space-indented block, or a `~~~` fence would pass. Acceptable for a hygiene guard.
- AC1 covers only `-r` / `--requirement`, per its literal wording; a dangling `-c` /
  `--constraint` (which Dependabot also follows) would reproduce the same abort. Widening the
  matcher is a spec amendment, not a review fix.
- `requirements-dev.txt` is not gitignored, so a future `make export-reqs-dev` output could be
  committed again. A pinned export would still pass AC1, so this is not a Dependabot regression
  risk; adding the two filenames to `.gitignore` is a cheap follow-up, out of this item's scope.

### Root cause remains a hypothesis

Per the spec and handoff, the tests assert repository hygiene — they do **not** prove Dependabot
recovered. Dependabot's file-fetch order is not observable from outside the runner. AC3 is what
actually proves the fix.
