# PUB-084 — DRY Review Standalone Batch: Implementation Summary

**Status:** Implementation Complete (all waves: 1, 2, 2b, 3, 4 and 5)
**Date:** 2026-09-27

One section per wave; each wave ships as its own PR.

## Wave 1 — Posted-state isolation (#296) and Instagram tenant option (#273)

### Files Changed

- `publisher_v2/src/publisher_v2/services/publishers/instagram.py` — `INSTAGRAM_SESSION_KEY = "default"` module constant; `tenant` constructor parameter and `self._tenant` removed; all 12 session-store calls use the constant; docstrings state the single-instance-per-database limit. `session_store` seam kept.
- `publisher_v2/src/publisher_v2/services/instagram_session.py` — docstrings only ("one row per key", single-instance note). Store method signatures unchanged; no schema change.
- `docs_v2/05_Configuration/CONFIGURATION.md` — "Instagram: one instance per database (#273)" note after the platform-secrets table in §1 (the document has no Instagram section of its own).
- `publisher_v2/tests/conftest.py` — autouse `_isolate_env` sets `XDG_CACHE_HOME` to `tmp_path_factory.mktemp("xdg-cache")` per test; `bypass_dedup` fixture deleted.
- `publisher_v2/tests/test_suite_hygiene.py` — new: AC1/AC2 ratchets.
- Deleted from 8 test files: seven `_isolated_posted_state` autouse fixtures and `_reset_cache` in `test_utils_support.py`.
- Deleted from 9 test files: 17 inline `setenv("XDG_CACHE_HOME", ...)` lines.
- Deleted from 7 test files: 42 isolation-only `load_posted_*`/`save_posted_*` no-op patches (behavioural patches in `test_workflow_metadata_selection.py` kept).
- `test_publishers_platforms.py` — six Instagram session-location tests now read the autouse `XDG_CACHE_HOME` instead of setting their own (assertions unchanged); `_SpyStore` records `(method, key)`; AC3 tests added.
- `test_utils_support.py` — two state tests rooted at the autouse `XDG_CACHE_HOME` (assertions unchanged).
- `test_storage_ops_metering_wiring.py` — `bypass_dedup` parameter removed from two tests.

Net: 28 files, +154 / −166 lines.

### Acceptance Criteria

- [x] AC1 — each test gets its own empty `XDG_CACHE_HOME` under pytest's temp dir (test: `test_posted_state_cache_is_isolated_per_test`, parametrised `[first]`/`[second]` to prove per-test; mutation-tested against a shared dir)
- [x] AC2 — no per-file `XDG_CACHE_HOME`, no `bypass_dedup`, no no-op posted-state patches (test: `test_no_per_file_posted_state_isolation`)
- [x] AC3 — no `tenant` parameter; one module-level session key (tests: `test_instagram_publisher_takes_no_tenant_argument`, `test_instagram_session_store_uses_one_key`, plus `test_instagram_relogin_uses_one_key` — an extra test, not in the handoff table, covering the relogin `clear`/`save` and back-off `set_blocked_until` path at the reviewer's request)

Manual check: running the eight previously unisolated files left `~/.cache/publisher_v2/posted.json` unchanged (same mtime and size).

### Test Results

1970 passed, 2 skipped, 0 failed under three random seeds (3349438808, 2300993560, 1113728778). Baseline before the wave: 1964 passed, 2 skipped.

### Quality Gates

- Format: ✅ (`ruff format --check .`, 261 files)
- Lint: ✅ (`ruff check .`)
- Type check: ✅ (`mypy`, 65 files, no issues)
- Tests: 1970 passed, 0 failed
- Coverage: 93.56% overall; `publishers/instagram.py` 99%, `instagram_session.py` 83%

### Subagent Verdicts

- `code-reviewer`: BLOCKED (resolved) → PASS WITH NITS. The first review found the "inline posted-hash patches that exist only for isolation" scope bullet not done; the test-engineer deleted the 42 patches and extended the AC2 guard. The remaining nit (six stale "Bypass dedup state" comments) was removed by the Lead as a comment-only edit.
- `security-auditor`: N/A — no change to `web/`, auth, secrets or config loading; Instagram session encryption unchanged.

### Linked Issues

- #296 — closed by the wave 1 PR (`Closes #296`)
- #273 — closed by the wave 1 PR (`Closes #273`)

### Notes

- Role split: #296 is test infrastructure only, so the test-engineer did both the red tests and the conftest/fixture changes; the developer (which never edits tests) did #273's source change.
- Lead decision: the six Instagram session-location tests were rewritten to read the autouse cache dir rather than allowlisted in the AC2 guard.
- The AC2 guard catches `setattr(..., lambda: set()|None)` forms only; `patch(..., return_value=set())` is not covered (none exist today).

## Wave 2 — Test infrastructure (#297, #298)

Test-only: no file under `publisher_v2/src` changed.

### Files Changed

- `publisher_v2/tests/caption_pipeline_fakes.py` — the one home for shared fakes: `FakeOpenAI` scripted mode (payloads, exceptions or callables replayed in order; records `calls` and `client_kwargs`), `FakeCompletion`, `fake_usage`, `stub_ai_service`, `MultiCaptionDummyGenerator`, the `BaseDummy*` classes moved from conftest, and `make_app_config(**overrides)`.
- `publisher_v2/tests/conftest.py` — fixtures only; `fake_openai` fixture; 19 unused fixtures deleted (`mock_full_env` kept: `env_first_config` uses it). Net −518 lines.
- Root tests — 12 files migrated off hand-rolled OpenAI chains, 10 off `AIService` subclasses and inline `_NoopLimiter`s; every root `ApplicationConfig(` goes through `make_app_config` (four thin wrappers over it kept in `test_workflow_multi_caption`, `test_caption_spec`, `test_pub028_smart_hashtags`, `test_sidecar_builders`).
- `publisher_v2/tests/web/conftest.py` — one real-app harness (`real_app_env`), per-key `FakeS3` with `managed_real_app`, `analyze_service`, hoisted library fixtures (`FEATURE_LIBRARY` unset inside; 52 `delenv` lines gone), `_FakeDropbox`/`_FakeBot`/`_FakeSMTP` defined once.
- Web tests — the two copied real-app harnesses, three `_FakeS3`s, three `_make_service` copies and the duplicated library fixtures replaced; 14 web `ApplicationConfig(` sites moved to `make_app_config` (equivalence checked by `model_dump()` comparison where built outside fixtures).
- `publisher_v2/tests/web/test_route_auth_matrix.py` — new: admin routes derived from the running app (endpoint and dependency source via AST, identity-matched to `require_admin`), 15 routes × 14 scenarios with the real guards, plus `test_every_mutating_route_is_admin_or_allowlisted` (only the two logout routes allowlisted).
- Deleted and folded into the matrix: `web/test_require_admin_strict_mode.py` (stale `app.py:476`-style ids), `web_integration/test_web_auth_integration.py`, the `_MUTATING` tests, `TestAuthEnforcement`, and `web_integration` require-admin tests that accepted any of 401/403/404.
- `web/test_web_app_additional.py` — error-path tests use a real admin session instead of no-op `require_auth`/`require_admin` patches.
- `test_web_thumbnail_endpoint.py::test_thumbnail_endpoint_requires_admin_when_auto_view_disabled` — expectation 401 → 403. The old 401 was the patched `require_admin`'s own `side_effect`; the test now runs the real guard. Reviewer and auditor both judged this a test fix, not a weakening.
- `web/test_library_delete_sanitizing.py` — re-seeded so only the listing check can refuse (`known.txt` seeded; `ghost.jpg` written behind the cached listing); both fail if `ensure_known_image` is a no-op.
- `web/test_csp_storage_origin.py` — `test_storage_origins_falls_back_without_lifespan_state` removes an order-dependent coverage swing in `middleware_security.py`.
- `publisher_v2/tests/test_suite_hygiene.py` — AC4-AC9 ratchets plus self-checks for the scan patterns.
- Placeholder secrets marked `# pragma: allowlist secret`; `.secrets.baseline` only shifted two line numbers.

### Acceptance Criteria

- [x] AC4 — `FakeOpenAI` replays a script; no hand-rolled OpenAI fakes (tests: `test_fake_openai_replays_script_in_order`, `test_no_hand_rolled_openai_fakes`; allowlist: `test_caption_eval_script.py`'s "never builds a client" tripwire)
- [x] AC5 — no `AIService` subclass in tests (test: `test_no_test_subclasses_ai_service`)
- [x] AC6 — every conftest fixture used (test: `test_every_conftest_fixture_is_used`)
- [x] AC7 — `make_app_config`; direct construction only in `test_config_managed.py`, which tests the model's validator (tests: `test_make_app_config_applies_overrides`, `test_application_config_built_via_helper`)
- [x] AC8 — each web fake defined once; per-key S3 head (tests: `test_web_fakes_defined_once`, `test_fake_s3_head_object_is_per_key`)
- [x] AC9 — route inventory covers every admin route, no line numbers; no auth patched out (tests: `test_route_inventory_covers_every_admin_route`, `test_no_test_patches_out_auth`). Extra, from the security audit: `test_every_mutating_route_is_admin_or_allowlisted`, and Basic-auth and strict-mode edge rows in the matrix.

### Test Results

2158 passed, 2 skipped under seeds 719490804 and 3994647 (wave 1 end: 1970). 48 old auth tests were folded into the matrix; the matrix and hygiene self-checks added the rest.

### Quality Gates

- Format / lint: ✅ · Type check: ✅ (no `src` change)
- Coverage: 93.55% overall. `services/ai.py` −0.13pp (line 440, the `TypeError` retry wave 5 deletes under AC18); no other `src` module moved beyond test-order noise, which the new `_storage_origins` test removes.

### Subagent Verdicts

- `code-reviewer`: PASS WITH NITS — gates green; exact-name traceability AC4-AC9; four mutation checks all caught (ratchets, a removed `require_admin`, a dropped inventory entry, a no-op `ensure_known_image`).
- `security-auditor` (run although the handoff schedules it for waves 3 and 5, because wave 2 rewrote the auth tests): PASS WITH NITS — no auth guarantee lost; a mutant removing the keep route's guard fails five tests. Its nits (opt-in route inventory, Basic and strict-mode rows, detect-secrets placeholders) were applied in this wave.

### Linked Issues

- #297 — closed by the wave 2 PR
- #298 — closed by the wave 2 PR

### Notes

- Some library tests still patch private route helpers (`_list_objects_buffered`, `_move_in_storage`), and the matrix's tenant scenario patches the middleware's orchestrator lookup. Neither is in wave 2's ACs; the helper patches go when #275 (PUB-056) moves that logic into storage.
- Web tests shrank by ~275 lines net rather than the issue's ~600 estimate because the auth matrix grew from 12 routes × 2 scenarios to 15 × 14.
- PUB-060's `minimal_ini_content` bullet is now obsolete (fixture deleted here).

## Wave 2b — Tooling (#295)

Pulled in from PUB-078 by the owner after waves 1 and 2 each needed several commit passes because the pre-commit hooks pinned an older ruff than `uv.lock`. Config only: no `publisher_v2/src` change.

### Files Changed

- `.pre-commit-config.yaml` — the `ruff-pre-commit` repo (v0.9.10) replaced by `repo: local` hooks running `uv run --frozen ruff format --force-exclude` and `uv run --frozen ruff check --fix --force-exclude` (`language: system`). `--force-exclude` keeps `pyproject` excludes applied when pre-commit passes filenames (without it the first run reformatted archived `code_v1/`, reverted); `--frozen` stops a commit from rewriting `uv.lock`.
- `.github/actions/setup/action.yml` — new composite action: `astral-sh/setup-uv` pinned to the same SHA `security-scan.yml` used (`d4b2f3b6…`, v5.4.2, with cache) and `uv sync --group dev --locked`. No `setup-python`: uv provides 3.12 from `.python-version`.
- `.github/workflows/code-quality.yml` (4 jobs), `security-scan.yml`, `caption-eval-nightly.yml` — each job keeps its own checkout, then uses the shared action; inline setup-python / setup-uv / `uv sync` steps removed. Jobs that used the floating `setup-uv@v5` tag now run the same commit, pinned.
- `security-scan.yml` — duplicate `--only-verified` TruffleHog step removed; "Verify .env not committed" runs `make check-secrets` (the Makefile's narrower alembic exclusion kept, which is stricter); echo-only "Check file permissions" step removed; `fetch-depth: 0` dropped (only TruffleHog needed it).
- `secret-scan.yml` — keeps the single TruffleHog step (default mode, the stricter one) and regains the weekly scan the removal would have lost: `schedule` (Mondays 09:00) and `workflow_dispatch` triggers, with `--only-verified` on those runs only. The pinned action scans full history on schedule events.
- `publisher_v2/tests/test_ci_security_gates.py` — AC21-AC24 tests plus `test_secret_scan_runs_a_weekly_full_history_verified_scan`; `test_every_action_in_the_security_workflows_is_pinned_by_sha` (Lead-authorised change) accepts only `./.github/actions/<name>` refs, requires each to resolve to an `action.yml`, and SHA-checks every `uses:` inside composite actions.
- `.claude/agent-memory/code-reviewer/` — the reviewer's note on CI-dedup review traps.

### Acceptance Criteria

- [x] AC21 — ruff hooks are `repo: local` running ruff through `uv run` (test: `test_precommit_ruff_uses_the_locked_version`)
- [x] AC22 — one TruffleHog step per pull-request and push event (test: `test_trufflehog_runs_once_per_event`)
- [x] AC23 — every job installs through `.github/actions/setup` after its own checkout (test: `test_every_job_installs_through_the_shared_setup_action`)
- [x] AC24 — `make check-secrets`, no echo-only steps (test: `test_security_scan_has_no_noop_steps`)
- Extra, from both reviews: `test_secret_scan_runs_a_weekly_full_history_verified_scan`.

### Descoped

- Dropping the redundant `--ignore-missing-imports`: `test_docs_commands.py` pins that exact command as the canonical mypy invocation across the Makefile, CLAUDE.md, AGENTS.md and contributor docs, so it stays everywhere, CI included.

### Test Results

2163 passed, 2 skipped. `actionlint` clean. Pre-commit ruff hooks pass on all files without rewriting any, running ruff 0.15.2 from `uv.lock`.

### Subagent Verdicts

- `code-reviewer`: PASS WITH NITS — every job's commands, env, permissions and triggers compared old vs new; eight mutations all caught. Nits (lost weekly scan, stale `fetch-depth`, inaccurate comment) applied.
- `security-auditor`: PASS WITH NITS — setup-uv SHA verified against the `v5.4.2` tag; composite pin check proven non-vacuous; `make check-secrets` stricter than the removed step. Recommended restoring the weekly verified full-history scan (done as specified) and `--frozen`/`--locked` (done).

### Linked Issues

- #295 — closed by the wave 2b PR
- #303 — filed from the audit: the gitleaks pre-commit hook scans only staged changes, so in CI it scans nothing. It predates this wave, and this wave does not fix it.

## Wave 3 — Browser tests and pruning (#299, #272, #300)

### Files Changed

- `publisher_v2/src/publisher_v2/web/templates/index.html` — the only production change (#272): the logout click handler is registered once in `initAdminControls()` instead of on every `disableButtons()` call (16 call sites; one click sent 10 POSTs). The explicit `X-Requested-With` header was dropped because the global fetch wrapper, installed first, adds it to every mutating request; the e2e flow now asserts the header on the wire.
- `pyproject.toml`, `uv.lock` — `pytest-playwright` dev dependency (owner-approved); `e2e` marker; default `addopts` deselect `-m "not e2e"`, so the default run and the commit hook need no browser.
- `.github/workflows/code-quality.yml` — new `e2e` job: checkout (`persist-credentials: false`), the shared setup action, `playwright install --with-deps chromium`, `pytest -m e2e`.
- `publisher_v2/tests/web/test_index_contract.py` — new: one page fetch, 48 parametrised rows for ids, attributes, zones, `hidden`/`admin-only` classes and select options. Replaces seven source-grep files (143 tests), deleted with the owner's approval.
- `publisher_v2/tests/e2e/` — new: the real app under uvicorn on `127.0.0.1:0`, `FakeS3` imported from `web/conftest`, an admin cookie minted with the app's signer, no fixed sleeps. Nine flows: upload lock (plus the grid refresh and the CSRF header), bulk-delete retry, one request per keep/remove/delete, one logout request carrying the CSRF header, per-platform caption limits, legacy caption shape on publish, and publish blocked on an empty platform caption.
- #300 pruning: upload stream tests merged into `web/test_library_upload.py` with four route-level cases re-added for deleted mocked ones; `test_requirements_files.py` 315 → 78 lines (a fenced-block regex keeps both guarantees; indented code blocks are no longer scanned); keep/remove config tests folded into `config/`; about 65 groups of identical tests parametrised or de-duplicated; tests of test doubles and existence-only tests deleted; `test_managed_storage`'s `to_thread` test rewritten as a behavioural "does not block the event loop" test (mutation-proven).
- `web_integration/test_web_admin_endpoints.py` — `test_auth_logout_cookie_only_without_xrw_is_csrf_blocked` pins CSRF on the logout path the UI calls (the existing test only covered the `/api/admin/logout` alias).
- `publisher_v2/tests/test_suite_hygiene.py` — AC10-AC12 ratchets. The source-grep guard flags `function <name>` and JS statement syntax (`const`/`let`/`var`, `=>`, `===`, statement `;`, `.addEventListener(`, identifier calls), while allowing element-contract checks.

### Acceptance Criteria

- [x] AC10 — no test greps `index.html` function bodies or statements; one parametrised element contract from one fetch (tests: `test_no_test_greps_index_html_function_bodies`, `test_index_exposes_required_hook`)
- [x] AC11 — the four required flows pass in a headless browser; default run deselects `e2e` (tests: `test_upload_queue_locks_controls_while_uploading`, `test_bulk_delete_retries_failed_items`, `test_curation_action_sends_one_request`, `test_logout_sends_one_request_after_repeated_actions`, `test_default_run_deselects_e2e`). Three further flows replace JS-statement greps found in review.
- [x] AC12 — no identical test bodies, empty allowlist (test: `test_no_identical_test_bodies`)

### Test Results

Default run: 2064 passed, 2 skipped, 9 deselected. `-m e2e`: 9 passed, stable across repeated runs (about 4s). Coverage 93.56% (missed lines 492 → 491; `web/routers/library.py` +0.23pp; no module dropped).

### Subagent Verdicts

- `code-reviewer`: PASS WITH NITS — gates green; mutations on the template (unfixed #272, broken upload lock, no-op retry, a dropped `multiple` attribute) each failed the right test; 15+ parametrised groups sampled with no weakened expectation. Nits applied: JS-statement greps the guard missed, a duplicate id test, a readable timeout on the curation flow, and the grid-refresh check.
- `security-auditor`: PASS WITH NITS — the fetch wrapper covers the logout POST, and a cookie-only logout without the header still gets 403; the e2e harness is loopback-only with placeholder secrets and no production change; the new dependencies have no known advisories; no security test lost in pruning. Nits applied: `persist-credentials: false`, the header assertion in e2e, and the committed `/api/auth/logout` CSRF test.

### Linked Issues

- #299, #272, #300 — closed by the wave 3 PR
- #305 — filed with the owner's agreement: UI behaviours that were pinned only by source greps and are not in the four spec'd flows (back-to-grid page, page-size persistence, 429 retry loop, queue clearing, Escape/ARIA, unload guards, plus two notes from review)

### Notes

- Some grep-only UI behaviours now have no test and are tracked in #305 (owner decision, option a).
- The `playwright install --with-deps` step downloads Chromium from Microsoft's CDN without a hash pin; exposure is limited by the job's read-only permissions and lack of secrets.
- `.gitleaks.toml` (owner-approved, option a): keeps gitleaks' default rules and allowlists only `^\.secrets\.baseline$`. Parametrising config tests moved two existing placeholder entries in the detect-secrets baseline; gitleaks' generic-api-key rule then read their unchanged SHA-1 hashes as newly added keys and blocked the commit. Checked against gitleaks v8.22.1's config schema; a fake key in any other file is still reported (verified with the hook's own binary). Pinned by `test_gitleaks_config_only_allowlists_the_detect_secrets_baseline`, which fails on any other allowlisted path or on any regex, stopword, commit or rule exclusion. The pattern is anchored, so it applies to repo-relative scans (as the hook runs); a manual `gitleaks dir /absolute/path` would still report the baseline.

## Wave 4 — Dead code (#294, #286)

No production behaviour change.

### Files Changed

- Deleted (owner decision on #294): `scripts/heroku_hetzner_clone.py` and its 919-line test `publisher_v2/tests/test_scripts_heroku_hetzner_clone.py`; the one-off docs-migration scripts `scripts/{migrate,cleanup,refine}_features.py` and `scripts/rename_artifacts.py`; `publisher_v2/src/publisher_v2/tools/__main__.py` (`python -m publisher_v2.tools.migrate_storage` still works through the module's own `__main__` guard); the `web/sidecar_parser.py` re-export shim (three tests now import `services.sidecar_parser`). `scripts/servers.txt` was never tracked; its `.gitignore` line stays so a local copy is never committed.
- `services/usage_meter.py` — one `_spawn_if_loop(coro) -> Task | None` (closes the coroutine when no loop is running); `emit_all` delegates every entry to `emit` instead of repeating its filter.
- `services/storage_ops_meter.py` — imports the same `_spawn_if_loop`; `stop_periodic_flush` alias, test-only `pending_batch_count` and the `_drain_loop` catch-all deleted (`_post_batch` catches every `Exception` and `_drain_pending` catches the drain timeout, so the catch-all was unreachable); `_PENDING_MAX = 12` module constant.
- `web/service.py` — calls `aclose()` where it called the deleted alias (same behaviour).
- Docs: the provisioning-script bullet in `docs_v2/01_Overview/README.md`, the #137 operator note in `CONFIGURATION.md` (reworded; operators must still unset `web_admin_pw`), `.cursor/commands/experts/hetzner.md`, reviewer memory, PUB-059's shim mention, and PUB-060's now-obsolete bullets (struck through, with a change-log line).
- Tests: `pending_batch_count()` → `len(meter._pending)`; the alias test became an `aclose` test with the same assertions; `test_drain_task_failure_is_logged_not_silent` deleted with the catch-all it exercised (`_post_batch`'s swallow-and-keep-pending guarantee stays pinned by four existing tests); one assertion that could no longer fail dropped.

### Acceptance Criteria

- [x] AC13 — the removed files are absent from the tracked tree and nothing live references them (test: `test_removed_scripts_are_not_referenced`). The check reads `git ls-files`, not the disk, so an untracked local copy (the owner's `scripts/servers.txt`) doesn't fail it. Historical records are exempt: archived trees, dated epics/reviews/test reports, `roadmap/archive/`, reviewer memory, and the specs that must name the files (listed one by one).
- [x] AC14 — one shared spawn helper; pending batches flushed on `aclose` (tests: `test_spawn_if_loop_without_running_loop_is_noop`, plus `test_spawn_if_loop_with_running_loop_returns_the_task`, `test_storage_ops_meter_has_no_alias_or_test_only_wrappers`, `test_pending_cap_is_a_module_constant`, `test_emit_all_delegates_every_entry_to_emit`). **Name mapping:** the handoff's `test_aclose_flushes_pending_batches` is satisfied by the existing `TestAclose::test_aclose_cancels_periodic_task_and_drains_pending` (the handoff row allowed keeping an equivalent); a mutation replacing the final drain with a no-op fails it.

### Test Results

2034 passed, 2 skipped, 9 deselected; `-m e2e` 9 passed. Coverage 93.59%; `usage_meter.py` 93% → 95%, `storage_ops_meter.py` 100% → 100%, `web/service.py` unchanged.

### Subagent Verdicts

- `code-reviewer`: BLOCKED (resolved) → fixed. The AC13 test checked disk existence, so the owner's untracked local `scripts/servers.txt` would have failed the suite and the pre-commit test hook in the main checkout after merge; and the `.gitignore` line for it had been removed, which would have un-ignored that file. Now the test checks tracked files and the ignore line is restored. Mutations on AC13 (a stale reference) and AC14 (an unclosed coroutine; a skipped final flush) were caught.
- `security-auditor`: N/A — no auth, secrets or config-loading change (one `web/service.py` call site renamed to `aclose()`).

### Linked Issues

- #294, #286 — closed by the wave 4 PR

## Wave 5 — Caption limits and JS dedup (#281, #277)

### Files Changed

- `utils/captions.py` — `smart_truncate` moved here (`services/ai.py` re-imports it; `ai.py` already imports this module, so the reverse would be circular); one `platform_caption_limit(platform)` lookup (unknown platforms fall back to generic; checks `model_fields` so a name like `copy` can't resolve to a pydantic method); `format_caption` ends with `smart_truncate`, so output never exceeds the limit and cuts at a sentence or word boundary. The FetLife/email path uses an ASCII `...` (`_sanitize_for_fetlife` exists because FetLife may strip `…`). `_trim_to_length` (which dropped hashtags while claiming to keep them) deleted. One `_HASHTAG_RE`; a shared emoji base class that each caller composes into exactly its previous class.
- `services/publishers/email.py` — in subject/both mode the subject is `prefix + smart_truncate(caption, limit - len(prefix), ellipsis="...")`, so `"Private: "`/`"Avatar: "` plus the caption fits FetLife's measured 240; the body keeps the full caption; the confirmation copy reuses the subject.
- `services/ai.py` — history narrowed to `dict[str, list[str]] | None` (also in `core/workflow.py`); the flat-list branch, `build_history_block` and `truncate_history_to_budget` deleted; the `TypeError` retry in `_create_vision_completion` removed (it re-sent the request without `max_tokens` to suit old test doubles and could hide real SDK errors); one module logger; one `_sha256_seed` for `senses_seed` and `sample_voice_examples`.
- `db/caption_store.py` — test-only `fetch_recent_by_platform` and unused `_DEFAULT_RETENTION_DAYS` deleted; remaining queries stay tenant-scoped.
- `utils/captions.py` `build_metadata_phase2` — a (field, key) table loop with one list-cleaning helper; output byte-identical.
- `web/templates/index.html` (#277, −140 lines) — one `postImageAction` for analyze/publish/keep/remove/delete (every message, endpoint and check order kept; publish's caption checks and confirm in `preparePublish`); `deleteLibraryObject`/`removeFromGrid`/`processDeleteQueue` for single, bulk and retry deletes; one `DEFAULT_FEATURES` (merged key by key with `??`, so a server `null` can't override a default and unknown keys aren't copied); one `fetchImageList` (the two caches stay separate); dead `#env-indicator` and `data.images` fallback removed. Accepted changes on single grid delete: the error toasts use the shared messages, and the selection label now updates.
- `docs_v2/02_Specifications/SPECIFICATION.md` — history section describes the current per-platform flow.
- Tests: AC15-AC18 targets; pins written against the old code before the refactor (both emoji classes, exact seed values, phase-2 metadata); FetLife ASCII-ellipsis tests for both paths; tests of deleted helpers retired, read-back and fetch tests repointed to `fetch_recent_with_angles_by_platform` (keeping ordering, limit and tenant-isolation coverage), four flat-history tests converted to the dict shape; two new e2e flows (analyze, single grid delete). The e2e harness now installs the scripted OpenAI fake before the server starts and points `OPENAI_BASE_URL` at `127.0.0.1:9`, so no test can reach the real API.

### Acceptance Criteria

- [x] AC15 — `format_caption` never exceeds the platform limit and cuts with `smart_truncate` (test: `test_format_caption_never_exceeds_platform_limit`, 25 cases; plus `test_fetlife_truncation_uses_ascii_ellipsis`)
- [x] AC16 — prefix + caption ≤ the email limit in every subject mode (tests: `test_prefixed_subject_never_exceeds_email_limit`, `test_fetlife_subject_truncation_uses_ascii_ellipsis`)
- [x] AC17 — phase-2 metadata byte-identical (test: `test_build_metadata_phase2_output_unchanged`, captured from the pre-refactor code)
- [x] AC18 — a vision `TypeError` propagates with one request (test: `test_vision_completion_type_error_is_not_retried`)
- [x] AC19 — `web/test_index_contract.py` unedited and every existing e2e flow body unchanged; all pass after the JS dedup. Analyze and single grid delete, the two actions no flow covered, gained e2e flows (mutation-checked: seven template mutants caught) in place of a manual smoke test.

### Caption-harness evidence

The handoff asks for a live caption-harness run against the PUB-080 baseline. The code reviewer instead dumped every prompt builder (`_build_multi_prompt` with dict/None/empty history, with and without voice examples), both seed functions, both emoji functions and `format_caption` for every platform on the same fixtures in `main` and in this branch: byte-identical except over-limit captions, the intended AC15 change. **No generated prompt text changes.** Whether this replaces the live run is the owner's call (recorded in the PR).

### Test Results

2087 passed, 2 skipped, 11 deselected; `-m e2e` 11 passed across repeated and random-order runs. Coverage 94%, every touched module unchanged (`utils/captions.py` 99%, `services/ai.py` 96%, `publishers/email.py` 96%, `db/caption_store.py` 97%, `utils/caption_metrics.py` 93%).

### Subagent Verdicts

- `code-reviewer`: PASS WITH NITS — gates green; guards confirmed green on the old code and targets red on it; mutations on AC15, AC16 and AC18 caught; behaviour outside the ACs byte-identical. Nits applied: selection label after single delete, ASCII ellipsis on the FetLife paths, test import from `utils.captions`.
- `security-auditor`: PASS — CSRF, admin gating, confirm-before-request order, URL encoding and CSP intact in the deduplicated JS; no new XSS sinks; the email subject is truncated before the header-injection guard; caption-store queries stay tenant-scoped; the e2e harness cannot reach OpenAI.

### Linked Issues

- #281, #277 — closed by the wave 5 PR
