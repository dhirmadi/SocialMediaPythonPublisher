# PUB-031 — Managed Storage Migration & Admin Library: Implementation Summary

**Status:** Implementation Complete
**Date:** 2026-04-12

## Files Created
- `publisher_v2/src/publisher_v2/tools/__init__.py` — Tools package init
- `publisher_v2/src/publisher_v2/tools/__main__.py` — Module runner for migration CLI
- `publisher_v2/src/publisher_v2/tools/migrate_storage.py` — Migration CLI (Dropbox → R2)
- `publisher_v2/src/publisher_v2/config/features.py` — Feature flag resolver (library_enabled)
- `publisher_v2/src/publisher_v2/web/routers/library.py` — Admin library API router (CRUD endpoints)
- `publisher_v2/tests/tools/__init__.py` — Test package init
- `publisher_v2/tests/tools/test_migrate_storage.py` — Migration CLI tests (16 tests)
- `publisher_v2/tests/web/test_library_api.py` — Library API tests (17 tests)
- `publisher_v2/tests/web/test_library_ui.py` — Library UI tests (8 tests)
- `publisher_v2/tests/test_library_feature_flag.py` — Feature flag tests (5 tests)

## Files Modified
- `publisher_v2/src/publisher_v2/config/schema.py` — Added `library_enabled` to FeaturesConfig
- `publisher_v2/src/publisher_v2/web/app.py` — Mounted library router; extended /api/config/features with library_enabled
- `publisher_v2/src/publisher_v2/web/templates/index.html` — Added library panel (admin-only, managed-only) with upload, delete, move, folder filter
- `docs_v2/03_Architecture/ARCHITECTURE.md` — Added library endpoints and migration CLI reference
- `pyproject.toml` / `uv.lock` — Added python-multipart dependency

## Acceptance Criteria
- [x] AC1 — Migration CLI validates env vars, exit code 1 on missing (test: `test_missing_env_vars_exit_1`, `test_cli_arg_parsing`)
- [x] AC2 — --dry-run lists without writing (test: `test_dry_run_lists_without_writing`, `test_dry_run_summary_counts`)
- [x] AC3 — Normal copy with sidecar support (test: `test_copies_image_and_sidecar`, `test_skips_sidecar_when_absent`)
- [x] AC4 — Subfolder structure preserved (test: `test_preserves_subfolder_structure_archive_keep_remove`)
- [x] AC5 — Idempotent skip/re-copy (test: `test_idempotent_skip_existing`, `test_recopy_on_hash_mismatch`)
- [x] AC6 — --limit N caps count (test: `test_limit_caps_copied_count`)
- [x] AC7 — Per-file error handling (test: `test_per_file_error_continues_and_summary`, `test_exit_code_1_on_errors`)
- [x] AC8 — No secrets in logs (test: `test_no_secrets_in_log_output`)
- [x] AC9 — GET /api/library/objects (test: `test_list_objects_managed`, `test_list_objects_404_dropbox`, `test_list_objects_paginated`)
- [x] AC10 — POST /api/library/upload with validation (test: `test_upload_jpeg_success`, `test_upload_rejects_disallowed_mime_415`, `test_upload_rejects_oversize_413`)
- [x] AC11 — Upload rate limit 10/min (test: `test_upload_rate_limit_429`)
- [x] AC12 — DELETE with sidecar (test: `test_delete_removes_image_and_sidecar`, `test_delete_404_not_found`)
- [x] AC13 — Move to target folder (test: `test_move_to_keep`, `test_move_to_archive`, `test_move_invalid_target_400`)
- [x] AC14 — Auth enforcement (test: `test_endpoints_require_auth_401`, `test_endpoints_require_admin_403`)
- [x] AC15 — Library panel visibility (test: `test_library_panel_visible_admin_managed`, `test_library_panel_hidden_dropbox`)
- [x] AC16 — Upload flow with client-side validation (test: `test_upload_input_exists`)
- [x] AC17 — Delete flow with confirmation (test: `test_delete_button_js_exists`)
- [x] AC18 — Move flow with dropdown (test: `test_move_dropdown_js_exists`, `test_folder_filter_exists`)
- [x] AC19 — Feature flag defaults/auto-enable (test: `test_library_enabled_defaults_to_false`, `test_library_enabled_auto_set_for_managed`, `test_library_disabled_by_env_override`)
- [x] AC20 — /api/config/features includes library_enabled (test: `test_features_endpoint_includes_library_enabled`)
- [x] AC21 — No credentials in responses (test: `test_no_credentials_in_responses_or_logs`)
- [x] AC22 — Preview mode not affected (library is web-only; migration is separate tool)
- [x] AC23 — Zero lint/mypy violations
- [x] AC24 — Tests cover all specified areas (46 new tests)
- [x] AC25 — ARCHITECTURE.md updated
- [x] AC26 — Cutover checklist in handoff doc (already present in PUB-031_handoff.md)

## Test Results
- 554 passed, 1 pre-existing failure (unrelated email publisher test)
- 46 new tests across 4 test files
- Format: zero reformats
- Lint: zero violations
- Type check: zero errors on touched files

## Quality Gates
- Format: pass
- Lint: pass
- Type check: pass
- Tests: 554 passed (46 new)

## Notes
- `python-multipart` added as dependency (required by FastAPI for multipart upload support)
- Library router accesses `ManagedStorage.client` and `._bucket` directly (as specified in design decision #7 from handoff) — typed as `Any` to satisfy mypy
- Rate limiting uses in-memory sliding window counter (no Redis dependency, resets on restart)
- Hash comparison between Dropbox content_hash and R2 ETag is best-effort (different algorithms)
