# PUB-084 — DRY Review Standalone Batch: Implementation Summary

**Status:** In Progress (waves 1, 2 and 2b complete; waves 3-5 remain)
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
