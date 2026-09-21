# PUB-060: Test and Docs Hygiene

| Field | Value |
|-------|-------|
| **ID** | PUB-060 |
| **Category** | Foundation |
| **Priority** | P2 |
| **Effort** | M |
| **Status** | Proposal |
| **Dependencies** | PUB-059 |

## User Story

As a platform maintainer, I want the test suite to pin product behaviour rather than repository state or prompt wording, and the documentation to describe the code that exists, so that a green suite means the product works and a new contributor is not told to use INI files.

## Problem

Review [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177), architecture A8 and D. Suite: 1,695 collected, 136 s, 157 files, about 33k lines (1.9× source), 94 files flat in the top-level test dir, `web_integration/` a 445-line tier overlapping `web/`. About 44 tests pin repository state (`test_env_centralization.py` pins exact env-read sets and AST node counts, ratifying 25 ad-hoc reads; `test_coverage_gate_config.py` nine tests on pyproject and CI text; `test_docs_commands.py` thirteen tests parsing AGENTS.md and CLAUDE.md). 59 tests assert on prompt wording and break on any rewording of `ai_prompts.yaml`. Six tests have no assertion. `web/test_web_service_coverage.py` exists to cover line numbers. `test_e2e_performance_telemetry.py` skips unless a workspace `.env` exists and never runs in CI. `conftest.py` rebinds `dotenv.load_dotenv` at import and per test, ships a stale INI fixture and clears a variable no code reads. Three commits this weekend restored tests clobbered by concurrent branches. Fourteen documentation contradictions: AGENTS.md still says INI and "HTTP auth + admin cookie"; ARCHITECTURE.md is version 2.6 from December 2025 with INI and DI claims; CONFIGURATION.md documents an INI load order in the same file that says INI is gone; SECURITY.md, README, two rules files and the CLAUDE.md package layout are stale. #145 closed without touching most of them.

## Desired Outcome

No allow-list test can grow; no test asserts on prompt wording; no test lacks an assertion; every test runs in CI; suite time not worse than today. Every listed documentation line corrected, with a grep test that keeps INI, password login and "Dropbox is source of truth" out of the documents.

## Scope

**In scope (tests, one PR each):**
- Allow-list tests converted to ratchets (pinned sets may only shrink)
- `web_integration/` folded into `web/`; top-level tests grouped into packages by `git mv`
- `test_web_service_coverage.py` replaced by behaviour tests or deleted once PUB-058 covers the paths
- The 59 wording tests rewritten to structural assertions (PUB-051 starts this for `test_ai_prompt_payload.py`)
- Six no-assert tests fixed or deleted; INI fixture and dead env clear removed; single dotenv rebind
- `test_e2e_performance_telemetry.py` run against fakes in CI or moved to the nightly job
- pydocstyle pre-commit hook dropped (closes #176)

**In scope (docs, one PR each):**
- `tests/test_docs_consistency.py` greps the listed documents for `INI`, `password login`, `web_admin_pw`, `Dropbox is source of truth`, `HTTP auth + ` and asserts CLAUDE.md's layout lists every top-level package
- AGENTS.md; ARCHITECTURE.md (version, date, stage pipeline, layering rule); CONFIGURATION.md (INI paragraphs out, precedence table in); README.md; SECURITY.md (CI gates); `.claude/rules/architecture.md`, `.claude/rules/testing.md`; CLAUDE.md layout

**Out of scope:**
- New tests for new behaviour (each PUB item carries its own)

## Acceptance Criteria

- AC1: Given an allow-list test, when a new entry is added to the pinned set, then the test fails; when an entry is removed, then it passes
- AC2: Given the suite, when it is searched for `assert "…" in <prompt>` patterns against rendered prompts, then none remain
- AC3: Given every test function, when collected, then each contains at least one assertion (a collection-time check)
- AC4: Given CI, when the suite runs, then no test is skipped for a missing local `.env`
- AC5: Given the suite before and after, when wall time is compared with `-p no:randomly`, then it is not worse than 136 s
- AC6: Given `test_docs_consistency.py`, when it runs on `main` before the doc PRs, then it fails on every listed contradiction; after them, then it passes
- AC7: Given ARCHITECTURE.md, when its header is read, then the version and date are current and the layering section matches `test_layering.py`
- AC8: Given the suite, when run three times with random seeds, then it passes each time

## Implementation Notes

- Two sub-issues: #211 (tests), #212 (docs, closes last on #177).
- Docs that describe something a Phase 4 item changes follow that item's merge.
- The collection-time assertion check can be a small pytest plugin in `conftest.py` using `ast` on each test function body.

## Risks

- Grouping tests by `git mv` touches 94 files; do it in one PR with no content change so review is a rename check.
- The docs grep test must allow an explicit "removed in #97" sentence; use a negative lookahead or an allow-list of exact sentences.

## Success Metrics

- Repo-state tests fall from about 44 to the ratchets and the layering guard.
- Zero wording-only test failures on the next prompt PR.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issues [#211](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/211), [#212](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/212); closes [#176](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/176)
- Prior fixes #135 (order-independent suite), #141 (coverage gate), #145 (docs drift), #167 (docstrings)
