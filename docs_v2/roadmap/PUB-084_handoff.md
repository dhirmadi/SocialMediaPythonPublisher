# Implementation Handoff: PUB-084 — DRY Review Standalone Batch

**Status:** Ready for implementation

## For Claude Code

### Sequencing

Five waves, one PR each, from branch `refactor/pub-084-dry-review-batch` in worktree
`../SocialMediaPythonPublisher-pub084` (its own `.venv`). Each wave rebases on `main` after the
previous wave merges. Each PR body carries `Closes #N` for the issues that wave resolves (AC20).

| Wave | Issues | ACs |
|------|--------|-----|
| 1 | #296, #273 | AC1-AC3 |
| 2 | #297, #298 | AC4-AC9 |
| 2b | #295 | AC21-AC24 |
| 3 | #299, #272, #300 | AC10-AC12 |
| 4 | #294, #286 | AC13-AC14 |
| 5 | #281, #277 | AC15-AC19 |

### Test-first targets

Ratchet tests (repo-state checks over `publisher_v2/tests` or `src`) live in
`publisher_v2/tests/test_suite_hygiene.py` unless noted.

| AC | Test name (exact function) | File |
|----|----------------------------|------|
| AC1 | `test_posted_state_cache_is_isolated_per_test` | `test_suite_hygiene.py` |
| AC2 | `test_no_per_file_posted_state_isolation` | `test_suite_hygiene.py` |
| AC3 | `test_instagram_publisher_takes_no_tenant_argument` | `test_publishers_platforms.py` |
| AC3 | `test_instagram_session_store_uses_one_key` | `test_publishers_platforms.py` |
| AC4 | `test_fake_openai_replays_script_in_order` | `test_caption_pipeline_fakes.py` |
| AC4 | `test_no_hand_rolled_openai_fakes` | `test_suite_hygiene.py` |
| AC5 | `test_no_test_subclasses_ai_service` | `test_suite_hygiene.py` |
| AC6 | `test_every_conftest_fixture_is_used` | `test_suite_hygiene.py` |
| AC7 | `test_make_app_config_applies_overrides` | `test_caption_pipeline_fakes.py` (or the shared fakes module's test) |
| AC7 | `test_application_config_built_via_helper` | `test_suite_hygiene.py` |
| AC8 | `test_web_fakes_defined_once` | `test_suite_hygiene.py` |
| AC8 | `test_fake_s3_head_object_is_per_key` | `web/test_web_harness.py` |
| AC9 | `test_route_inventory_covers_every_admin_route` | `web/test_route_auth_matrix.py` |
| AC9 | `test_no_test_patches_out_auth` | `test_suite_hygiene.py` |
| AC21 | `test_precommit_ruff_uses_the_locked_version` | `test_ci_security_gates.py` |
| AC22 | `test_trufflehog_runs_once_per_event` | `test_ci_security_gates.py` |
| AC23 | `test_every_job_installs_through_the_shared_setup_action` | `test_ci_security_gates.py` |
| AC24 | `test_security_scan_has_no_noop_steps` | `test_ci_security_gates.py` |
| AC10 | `test_no_test_greps_index_html_function_bodies` | `test_suite_hygiene.py` |
| AC10 | `test_index_exposes_required_hook` (parametrised) | `web/test_index_contract.py` |
| AC11 | `test_upload_queue_locks_controls_while_uploading` | `e2e/test_admin_flows.py` |
| AC11 | `test_bulk_delete_retries_failed_items` | `e2e/test_admin_flows.py` |
| AC11 | `test_curation_action_sends_one_request` (parametrised keep/remove/delete) | `e2e/test_admin_flows.py` |
| AC11 | `test_logout_sends_one_request_after_repeated_actions` | `e2e/test_admin_flows.py` |
| AC11 | `test_default_run_deselects_e2e` | `test_suite_hygiene.py` |
| AC12 | `test_no_identical_test_bodies` | `test_suite_hygiene.py` |
| AC13 | `test_removed_scripts_are_not_referenced` | `test_suite_hygiene.py` |
| AC14 | `test_spawn_if_loop_without_running_loop_is_noop` | `test_storage_ops_meter.py` |
| AC14 | `test_aclose_flushes_pending_batches` | `test_storage_ops_meter.py` (keep if an equivalent exists; record its name) |
| AC15 | `test_format_caption_never_exceeds_platform_limit` (parametrised over platforms and lengths) | `test_captions_formatting.py` |
| AC16 | `test_prefixed_subject_never_exceeds_email_limit` (parametrised over `normal`/`private`/`avatar`) | `test_publishers_platforms.py` |
| AC17 | `test_build_metadata_phase2_output_unchanged` | `test_captions_metadata.py` |
| AC18 | `test_vision_completion_type_error_is_not_retried` | `test_ai_error_paths.py` |
| AC19 | the AC10 and AC11 tests, unedited | — |

Where a named file does not exist, create it; where an equivalent test already exists under a
different name, keep it and record the mapping in the summary.

### Mock boundaries

- External services only: OpenAI (`FakeOpenAI`), S3 (`FakeS3`), Telegram, SMTP, Auth0. Never
  patch `require_auth`/`require_admin`, private route helpers, or `utils.state` functions.
- `e2e`: real app under uvicorn on a free port, `FakeS3`-backed managed storage, admin cookie
  minted with the app's own signer. No network beyond localhost.

### E2E setup (wave 3)

- `uv add --group dev pytest-playwright` (approved by the owner's delegation, recorded in the spec).
- `pyproject.toml`: register marker `e2e`; add `-m "not e2e"` to the default `addopts` so
  `uv run pytest` and the pre-commit test hook need no browser.
- CI: new job in `code-quality.yml` running `uv run playwright install --with-deps chromium`
  then `uv run pytest -m e2e`. SHA-pin any new action.
- Tests wait on DOM state or network responses (`expect(...)`, `page.expect_request`), never
  fixed sleeps.

### Files likely touched

- Wave 1: `tests/conftest.py`, seven test files with `_isolated_posted_state`,
  `tests/test_storage_ops_metering_wiring.py`, `services/publishers/instagram.py`,
  `services/instagram_session.py` (docstrings), `docs_v2/05_Configuration/CONFIGURATION.md`.
- Wave 2: `tests/caption_pipeline_fakes.py`, `tests/conftest.py`, ~30 root test files,
  `tests/web/conftest.py`, ~20 web test files.
- Wave 3: `pyproject.toml`, `uv.lock`, `.github/workflows/code-quality.yml`,
  `web/templates/index.html` (logout only), six UI test files replaced, `tests/e2e/`.
- Wave 4: `scripts/`, `tools/__main__.py`, `web/sidecar_parser.py`, `services/usage_meter.py`,
  `services/storage_ops_meter.py`, `web/service.py` (call site), two docs, PUB-060 spec.
- Wave 5: `utils/captions.py`, `services/ai.py`, `utils/caption_metrics.py`,
  `services/publishers/email.py`, `web/templates/index.html`.

### Non-negotiables

- Waves 2-4: no production behaviour change; coverage ≥85% overall and ≥80% on touched modules;
  per-module coverage compared before and after each pruning commit.
- Wave 5: live caption-harness run against the PUB-080 baseline recorded in the PR body;
  manual browser smoke of every admin action recorded in the PR body.
- Never edit a test's expectation to make it pass; diagnose per `.claude/rules/testing.md`.
- `code-reviewer` on every wave; `security-auditor` on waves 3 and 5 (they touch `web/` templates
  and the email publisher).

### Claude Code command

```
/implement PUB-084
```
