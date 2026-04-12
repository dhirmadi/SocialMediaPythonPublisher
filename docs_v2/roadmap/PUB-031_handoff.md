# Implementation Handoff: PUB-031 — Managed Storage Migration & Admin Library

**Hardened:** 2026-03-16
**Status:** Ready for implementation

## For Claude Code

### Test-first targets

| AC | Test file | Key test cases |
|----|-----------|----------------|
| AC1 | `publisher_v2/tests/tools/test_migrate_storage.py` | `test_missing_env_vars_exit_1`, `test_cli_arg_parsing` |
| AC2 | `publisher_v2/tests/tools/test_migrate_storage.py` | `test_dry_run_lists_without_writing`, `test_dry_run_summary_counts` |
| AC3 | `publisher_v2/tests/tools/test_migrate_storage.py` | `test_copies_image_and_sidecar`, `test_skips_sidecar_when_absent` |
| AC4 | `publisher_v2/tests/tools/test_migrate_storage.py` | `test_preserves_subfolder_structure_archive_keep_remove` |
| AC5 | `publisher_v2/tests/tools/test_migrate_storage.py` | `test_idempotent_skip_existing`, `test_recopy_on_hash_mismatch` |
| AC6 | `publisher_v2/tests/tools/test_migrate_storage.py` | `test_limit_caps_copied_count` |
| AC7 | `publisher_v2/tests/tools/test_migrate_storage.py` | `test_per_file_error_continues_and_summary`, `test_exit_code_1_on_errors` |
| AC8 | `publisher_v2/tests/tools/test_migrate_storage.py` | `test_no_secrets_in_log_output` |
| AC9 | `publisher_v2/tests/web/test_library_api.py` | `test_list_objects_managed`, `test_list_objects_404_dropbox`, `test_list_objects_paginated` |
| AC10 | `publisher_v2/tests/web/test_library_api.py` | `test_upload_jpeg_success`, `test_upload_png_success`, `test_upload_rejects_disallowed_mime_415`, `test_upload_rejects_oversize_413` |
| AC11 | `publisher_v2/tests/web/test_library_api.py` | `test_upload_rate_limit_429` |
| AC12 | `publisher_v2/tests/web/test_library_api.py` | `test_delete_removes_image_and_sidecar`, `test_delete_404_not_found` |
| AC13 | `publisher_v2/tests/web/test_library_api.py` | `test_move_to_keep`, `test_move_to_archive`, `test_move_invalid_target_400` |
| AC14 | `publisher_v2/tests/web/test_library_api.py` | `test_endpoints_require_auth_401`, `test_endpoints_require_admin_403` |
| AC15 | `publisher_v2/tests/web/test_library_ui.py` | `test_library_panel_visible_admin_managed`, `test_library_panel_hidden_dropbox`, `test_library_panel_hidden_non_admin` |
| AC16-18 | `publisher_v2/tests/web/test_library_ui.py` | Client-side behavior — manual verification + snapshot tests if feasible |
| AC19 | `publisher_v2/tests/test_config_managed.py` | `test_library_enabled_auto_set_for_managed`, `test_library_disabled_by_env_override`, `test_library_disabled_for_dropbox` |
| AC20 | `publisher_v2/tests/web/test_library_api.py` | `test_features_endpoint_includes_library_enabled` |
| AC21 | `publisher_v2/tests/web/test_library_api.py` | `test_no_credentials_in_responses_or_logs` |
| AC23 | (quality gate) | `uv run ruff check .` + `uv run mypy . --ignore-missing-imports --exclude=venv --exclude=env` |
| AC24 | All above test files | Aggregate pass |

### Mock boundaries

| External service | Mock strategy | Existing fixture / notes |
|-----------------|---------------|--------------------------|
| Dropbox SDK (`dropbox.Dropbox`) | `unittest.mock.patch` on `DropboxStorage` methods | See `tests/conftest.py` — `BaseDummyStorage` already available; for migration, mock `DropboxStorage` directly |
| S3 / boto3 | `unittest.mock.patch` on `ManagedStorage` methods or `boto3.client` | See `tests/test_managed_storage.py` — existing mock patterns for `client.get_object`, `client.put_object`, etc. |
| FastAPI test client | `httpx.AsyncClient` via `app` fixture | See `tests/web/test_web_service.py` for patterns |
| File uploads | `UploadFile` mock or `httpx` multipart | Standard FastAPI testing pattern |

### Files to create

| Area | File |
|------|------|
| Migration tool | `publisher_v2/src/publisher_v2/tools/__init__.py` |
| Migration tool | `publisher_v2/src/publisher_v2/tools/migrate_storage.py` |
| Library router | `publisher_v2/src/publisher_v2/web/routers/library.py` |
| Library models | `publisher_v2/src/publisher_v2/web/models.py` (extend existing) |
| Migration tests | `publisher_v2/tests/tools/__init__.py` |
| Migration tests | `publisher_v2/tests/tools/test_migrate_storage.py` |
| Library tests | `publisher_v2/tests/web/test_library_api.py` |
| Library UI tests | `publisher_v2/tests/web/test_library_ui.py` |

### Files to modify

| Area | File | Changes |
|------|------|---------|
| Config | `publisher_v2/src/publisher_v2/config/schema.py` | Add `library_enabled` to `FeaturesConfig` |
| Web app | `publisher_v2/src/publisher_v2/web/app.py` | Mount library router; extend `/api/config/features` with `library_enabled`; auto-set `library_enabled` for managed |
| Web models | `publisher_v2/src/publisher_v2/web/models.py` | Add `LibraryObjectResponse`, `LibraryListResponse`, `LibraryUploadResponse`, `LibraryMoveRequest`, `LibraryDeleteResponse` |
| Web template | `publisher_v2/src/publisher_v2/web/templates/index.html` | Add library panel (admin-only, managed-only) |
| Logging | `publisher_v2/src/publisher_v2/utils/logging.py` | Ensure `SanitizingFilter` covers `MIGRATE_DROPBOX_REFRESH_TOKEN` |
| Existing config tests | `publisher_v2/tests/test_config_managed.py` | Add `library_enabled` feature flag tests |
| Architecture docs | `docs_v2/03_Architecture/ARCHITECTURE.md` | Add library endpoints and migration CLI reference |

### Key design decisions (resolved during hardening)

1. **Dual-backend in migration**: Tool builds `DropboxStorage` and `ManagedStorage` directly from env vars — does NOT use `ApplicationConfig` or `create_storage()`. This avoids the model validator that forbids both providers.

2. **Hash comparison is best-effort**: Dropbox `content_hash` and R2 `ETag` use different algorithms (Dropbox uses a custom chunked hash; R2/S3 ETag is MD5 for non-multipart uploads). For `--resume`, the primary gate is **existence** of the target key. Hash comparison is logged as a warning on mismatch and triggers re-copy, but is not a reliable equality check. Document this clearly.

3. **Upload is server-side**: Files are uploaded through the Publisher (not via presigned URLs to R2). This means:
   - R2 credentials never reach the browser
   - Body size is limited server-side (20 MB default)
   - Publisher handles sanitization and validation
   - Trade-off: large files transit through the Publisher dyno (acceptable for photo uploads)

4. **Library router pattern**: Follows `web/routers/auth.py` as the model — `APIRouter` with prefix, mounted via `app.include_router()`. Each endpoint uses `Depends(get_request_service)` for storage/config, plus `require_auth` + `require_admin`.

5. **Rate limiting**: Simple in-memory sliding window counter keyed by admin cookie value. No Redis or external store. Resets on dyno restart (acceptable for v1).

6. **Sidecar metadata on managed storage**: `build_metadata_phase1` receives `dropbox_file_id=None, dropbox_rev=None` for managed storage (these fields are simply omitted from the sidecar). Migrated sidecars retain their original Dropbox metadata byte-for-byte. No migration of sidecar *content* is needed.

7. **`list_objects` vs `list_images`**: The library `GET /api/library/objects` needs file size and last_modified metadata, which `StorageProtocol.list_images` does not return (it returns filenames only). The library router will access `service.storage.client` (the boto3 client) directly via `asyncio.to_thread` using `list_objects_v2` paginator, or a new helper method on `ManagedStorage`. Prefer adding a `list_objects_detailed()` method on `ManagedStorage` to keep the boto3 client encapsulated.

### Non-negotiables for this item

- [ ] **Preview mode**: Not affected — migration CLI is a separate tool; library is web-only
- [ ] **Secrets**: No R2/Dropbox credentials in logs, API responses, or browser; `SanitizingFilter` covers migration env vars
- [ ] **Auth**: All library endpoints gated behind `require_auth` + `require_admin`; no weakening
- [ ] **Coverage**: ≥80% on new modules (`tools/migrate_storage.py`, `web/routers/library.py`)

### Cutover checklist (include in docs)

1. Run migration with `--dry-run` — verify file count matches Dropbox listing
2. Run migration (full copy) — review summary `{copied, skipped, errors}`
3. Verify objects in R2 (`aws s3 ls s3://publisher-media/tenant/instance/ --endpoint-url ...`)
4. In orchestrator admin: update instance `storage_provider` to `"managed"` and assign credential ref
5. Visit publisher admin UI — verify thumbnails load from managed storage
6. **Do not publish until cutover is verified** — archival during transition may target wrong backend
7. Rollback: revert orchestrator `storage_provider` to `"dropbox"` (Dropbox content is untouched — migration copies, does not move)

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-031_managed-storage-migration-admin-library.md
```
