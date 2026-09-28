# PUB-060: Test and Docs Hygiene

| Field | Value |
|-------|-------|
| **ID** | PUB-060 |
| **Category** | Foundation |
| **Priority** | P2 |
| **Effort** | M |
| **Status** | Proposal |
| **Dependencies** | PUB-059 |
| **Absorbs** | PUB-070 (Starlette TestClient cookie migration — test-suite change, same domain) |

## User Story

As a platform maintainer, I want the test suite to pin product behaviour rather than repository state or prompt wording, and the documentation to describe the code that exists, so that a green suite means the product works and a new contributor is not told to use INI files.

## Problem

Review [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177), architecture A8 and D. Suite: 1,695 collected, 136 s, 157 files, about 33k lines (1.9× source), 94 files flat in the top-level test dir, `web_integration/` a 445-line tier overlapping `web/`. About 44 tests pin repository state (`test_env_centralization.py` pins exact env-read sets and AST node counts, ratifying 25 ad-hoc reads; `test_coverage_gate_config.py` nine tests on pyproject, Makefile and CI text; `test_docs_commands.py` thirteen tests parsing AGENTS.md and CLAUDE.md; also `test_test_isolation.py`, `test_docs_feature_flags.py`); some are legitimate guards (`test_layering.py`), the concern is allow-lists that ratify debt. 59 tests (regex heuristic; the true count is likely higher) assert on prompt wording and break on any rewording of `ai_prompts.yaml`: `test_caption_context_intelligence.py` 15, `test_ai_prompt_payload.py` 10, `test_pub028_smart_hashtags.py` 8, `test_caption_history_db.py` 6. Six tests have no assertion. `web/test_web_service_coverage.py` exists to cover line numbers (its header still lists "Line 51 … Lines 80-86"). `test_e2e_performance_telemetry.py` skips unless a workspace `.env` exists (`:117`, `:122`) and never runs in CI. `conftest.py` rebinds `dotenv.load_dotenv` across all loaded modules at import (`:65-85`) and again per test, ships a stale `minimal_ini_content` fixture (`:292`) and clears `AUTH0_AUTHORIZED_EMAILS` (`:199`), which no code reads (code reads `ADMIN_LOGIN_EMAILS` / `AUTH0_ADMIN_EMAIL_ALLOWLIST`). Script tests dwarf module tests (919 lines for `scripts/heroku_hetzner_clone.py`, 748 for `scripts/caption_sample.py`). Three commits this weekend restored tests clobbered by concurrent branches. Fourteen documentation contradictions: AGENTS.md still says INI and "HTTP auth + admin cookie"; ARCHITECTURE.md is version 2.6 from December 2025 with INI and DI claims; CONFIGURATION.md documents an INI load order in the same file that says INI is gone; SECURITY.md, README, two rules files and the CLAUDE.md package layout are stale. #145 closed without touching most of them. Two docstring linters run with the same convention: the pydocstyle 6.3.0 hook cannot parse PEP 695 generics (`class RuntimeConfigCache[K, V]`, `class CredentialCache[K, V]`), prints "Cannot parse file" and reports those modules clean, while ruff `D` (enabled in #167) checks them (#176). Four code comments and labels found during #167 are also stale (#175).

## Desired Outcome

No allow-list test can grow; no test asserts on prompt wording; no test lacks an assertion; every test runs in CI; suite time not worse than today. Every listed documentation line corrected, with a grep test that keeps INI, password login and "Dropbox is source of truth" out of the documents.

## Scope

**In scope (tests, one PR each):**
- Allow-list tests converted to ratchets (pinned sets may only shrink)
- `web_integration/` folded into `web/`; top-level tests grouped into `ai/`, `workflow/`, `storage/`, `config/` packages by `git mv` (no content change)
- `test_web_service_coverage.py` replaced by behaviour tests for the same paths, or deleted once PUB-058 covers them
- **(From PUB-070)** Migrate off `TestClient`'s per-request `cookies=` kwarg: 83 deprecation warnings across `test_library_api.py` and `test_library_sort_filter.py`. Switch to client-level cookies or a fresh client per request (the pattern `conftest.py:154` already uses for uploads). Confirm the negative auth assertions (`require_admin` returns 401/403) still fail when the guard is stubbed out — a mutation check, per PUB-055's convention
- The 59 wording tests rewritten to structural assertions (message count, directive count, example block present or absent, JSON keys). PUB-051 (Done) started this: its new tests assert structure and the web fake routes on call shape instead of the `"sd_caption"` substring. The wording assertions still in `test_ai_prompt_payload.py` and the other three files remain this item's work
- Six no-assert tests given an assertion or deleted: `test_storage_ops_meter.py:77`, ~~`test_scripts_heroku_hetzner_clone.py:670`~~ (obsolete: the clone script and its test were deleted by PUB-084 wave 4), `test_storage_error_paths.py:214`, `config/test_loader_env_helpers.py:124, 133`, `web/test_publishers_endpoint.py:10` (a fixture named `test_client`; line numbers from #211)
- `conftest.py`: ~~`minimal_ini_content` fixture~~ (obsolete: already removed by PUB-084 wave 2) and the `AUTH0_AUTHORIZED_EMAILS` clear removed; the import-time dotenv rebind removed, keeping the per-test one
- `test_e2e_performance_telemetry.py` run against fakes in CI or moved to the nightly job
- pydocstyle pre-commit hook dropped (closes #176), after re-confirming ruff parity with a deliberately broken docstring for each of D100, D101, D102, D103, D107, D205 and D415. The hook's exclude comment in `.pre-commit-config.yaml` goes with it (its `tests`/`alembic`/`code_v1` exclusions are already in ruff's config), and the hook lists in `CLAUDE.md:44` and `AGENTS.md:28` drop pydocstyle

**In scope (docs, one PR each):**
- `tests/test_docs_consistency.py` greps the listed documents for `INI`, `password login`, `web_admin_pw`, `Dropbox is source of truth`, `HTTP auth + ` and asserts CLAUDE.md's layout lists every top-level package
- AGENTS.md; ARCHITECTURE.md (version, date, stage pipeline, layering rule); CONFIGURATION.md (INI paragraphs out, precedence table in); README.md; SECURITY.md (CI gates); `.claude/rules/architecture.md`, `.claude/rules/testing.md`; CLAUDE.md layout. The listed lines are the fourteen contradictions in #212, re-checked on `main` at `949b2d1` (2026-09-27) where a current line is given:
  1. `AGENTS.md:46` "Use `.env` + INI config" and `:151` "Secrets come from `.env` and INI config files"
  2. `AGENTS.md:47` "admin requires HTTP auth + server-enforced admin cookie" (a cookie alone satisfies `require_auth`; Auth0 is the only admin login, #137)
  3. `.claude/rules/architecture.md:15` "Storage: Dropbox is source of truth" (managed storage is the orchestrator path)
  4. `.claude/rules/architecture.md` "all orchestration lives here" while `web/service.py` is a second orchestrator (follows PUB-058, whose AC10 rewrites this file)
  5. `ARCHITECTURE.md:3-4` "Version: 2.6 / Last Updated: December 21, 2025"; `:36`, `:216` "Dynamic Layer: `.env` + INI"
  6. `ARCHITECTURE.md:11-19` Application → Domain → Infrastructure with DI, while `core/workflow.py` imports concrete services (follows PUB-058)
  7. `CONFIGURATION.md` INI lines contradicting its own `:76` removal note: `:121-122` "(from INI)", `:320` "Dynamic | `.env` + INI", `:326` load-order step "INI file parsed and validated", `:350` "Use INI for deployment-specific folders", `:353` "Put secrets in INI", `:362` "maintaining backward compatibility", and the INI fallback/migration text at `:427-479`
  8. `README.md:27` "Dropbox as source of truth for images"; `README.md:158` describes the pre-#137 image-route auth
  9. `SECURITY.md:96`, `:110` ignore `*.ini` and `chmod 600 configfiles/*.ini`
  10. `config/schema.py:376` `WebConfig` docstring "future INI-based overrides" on fields nothing reads (follows PUB-057, which deletes the fields)
  11. `.claude/rules/testing.md:28` lists Dropbox as the canonical dependency to mock
  12. `tests/conftest.py` INI fixture and dead env clear (the tests bullet above)
  13. `.claude/rules/web-security.md:14` names `WEB_ADMIN_COOKIE_TTL_SECONDS` (true) while `WebConfig.admin_cookie_ttl_seconds` claims to be the setting (dead; resolved by PUB-057 deleting the field)
  14. `CLAUDE.md` package layout omits `db/` and `tools/`
- Stale code comments and labels (#175), one small PR: `utils/preview.py:265` prints "Config File:" although INI is gone and `--config` is ignored (relabel as the config source or drop the line); ~~dead `normalize_name` at `scripts/migrate_features.py:43` deleted (not the used one in `refine_features.py`)~~ (obsolete: both scripts were deleted by PUB-084 wave 4); `config/source.py:253` `OrchestratorConfigSource` docstring "Full implementation is added in Stories 02-05" corrected; `web/models.py:127` `action: str  # "keep" or "remove"` corrected to the three values the code produces (`"delete"` included, with an empty `destination_folder`) or removed in favour of the class docstring

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
- AC9: Given each test PR, when its pass count is compared with `main`, then it is the same minus the deliberate deletions listed in that PR body
- AC10: Given `.pre-commit-config.yaml`, when it is read, then exactly one docstring linter (ruff `D`) runs, covering every file including the PEP 695 modules; and `CLAUDE.md`'s and `AGENTS.md`'s hook lists match the config
- AC14 (from PUB-070): Given `uv run pytest -q`, then no `DeprecationWarning` from `starlette/testclient.py` about per-request cookies is emitted
- AC15 (from PUB-070): Given `require_admin` neutered, when the negative auth tests run, then they fail — mutation check recorded in the summary, per PUB-055 convention
- AC11: Given a deliberately broken docstring in `config/runtime_cache.py`, when the pre-commit hooks run, then the run fails
- AC12: Given the #212 list above, when the doc PRs are merged, then every listed line is corrected or deleted
- AC13: Given `--preview` output, when it is read, then it does not claim to read a config file; ~~and `scripts/migrate_features.py` has no `normalize_name`~~ (obsolete: the script was deleted by PUB-084 wave 4), no docstring describes shipped work as forthcoming (`config/source.py`), and the `CurationResponse.action` comment matches the three values or is gone

## Implementation Notes

- Two sub-issues: #211 (tests), #212 (docs, closes last on #177).
- Docs that describe something a Phase 4 item changes follow that item's merge.
- The collection-time assertion check can be a small pytest plugin in `conftest.py` using `ast` on each test function body.
- The tests work runs after PUB-059 (the web factory removes the need for several `conftest.py` resets).
- The grep test lands with the first doc PR. To reconcile that with AC6, the documents not yet fixed can be listed as known hits that each later doc PR removes, so the test is green at every merge and fails on any new hit.
- Verification (from #211, #212): `uv run ruff format --check . && uv run ruff check .`; `for s in 1 2 3; do WEB_SESSION_SECRET=x uv run pytest -q -p no:cacheprovider -p randomly --randomly-seed=$RANDOM || exit 1; done`; `WEB_SESSION_SECRET=x uv run pytest -q -p no:cacheprovider -k "docs"`.

## Risks

- Grouping tests by `git mv` touches 94 files; do it in one PR with no content change so review is a rename check.
- The docs grep test must allow an explicit "removed in #97" sentence; use a negative lookahead or an allow-list of exact sentences.

## Success Metrics

- Repo-state tests fall from about 44 to the ratchets and the layering guard.
- Zero wording-only test failures on the next prompt PR.

## Related

- Tracker [#177](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/177); sub-issues [#211](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/211), [#212](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/212); closes [#176](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/176) and [#175](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/175). #211, #212, #176 and #175 were folded into this spec on 2026-09-27 and are tracked here
- PUB-051 (Done) started the wording-test rewrite; PUB-057 deletes the dead `WebConfig` fields behind contradictions 10 and 13; PUB-058 rewrites the layering and orchestration docs behind contradictions 4 and 6
- [PUB-070](archive/PUB-070_starlette-testclient-cookie-migration.md) — absorbed into this item (2026-09-27 roadmap review); parent tracker [#243](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/243)
- Prior fixes #135 (order-independent suite), #141 (coverage gate), #145 (docs drift), #167 (docstrings)

## Change Log

- 2026-09-27 — Absorbed PUB-070 (Starlette TestClient cookie migration) — same domain (test-suite hygiene), same priority (P2). Added its scope as a bullet, its ACs as AC14/AC15. PUB-070 moved to archive/ as Absorbed.
- 2026-09-27 — Folded in #211, #212, #176 and #175 so they can close as "tracked in PUB-060". Added from #211: the repo-state and wording-test file lists, the four test packages, the structural-assertion kinds, the six no-assert test locations, "keep the per-test dotenv rebind", the ordering after PUB-059, and the pass-count gate (AC9). Added from #212: the fourteen contradictions, re-checked at `main` `949b2d1` (moved lines updated: `CONFIGURATION.md` INI lines, `ARCHITECTURE.md:216`, `schema.py:376`, `web-security.md:14`), the grep test landing with the first doc PR, and AC12 (every listed line corrected). Added from #176: the ruff parity check, the exclude-comment and hook-list updates (including `AGENTS.md:28`, which #176 did not name), AC10 and AC11. Added #175's four stale comments and labels as a docs-in-code bullet with AC13. Recorded that PUB-051 (Done) has started the wording-test rewrite.
- 2026-09-28 — Marked obsolete, superseded by PUB-084: the `test_scripts_heroku_hetzner_clone.py` no-assert test and the `migrate_features.py` `normalize_name` deletion (scope bullet and AC13 clause) — wave 4 deleted the clone script, its test and the docs-migration scripts; the `minimal_ini_content` fixture removal — wave 2 already removed it.
