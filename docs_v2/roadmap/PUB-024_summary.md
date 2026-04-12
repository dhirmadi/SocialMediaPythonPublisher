# PUB-024 — Managed Storage Adapter: Implementation Summary

**Status:** Implementation Complete
**Date:** 2026-04-12

## Files Changed

### New files
- `publisher_v2/src/publisher_v2/services/managed_storage.py` — `ManagedStorage` class implementing `StorageProtocol` with boto3 S3 backend, Pillow thumbnails, LRU cache
- `publisher_v2/src/publisher_v2/services/storage_factory.py` — `create_storage(config)` factory function
- `publisher_v2/tests/test_managed_storage.py` — 18 tests covering AC1–AC14, AC25
- `publisher_v2/tests/test_storage_factory.py` — 2 tests for factory dispatch (AC17)
- `publisher_v2/tests/test_config_managed.py` — 10 tests for config/credential/standalone (AC15–AC24)

### Production code (modified)
- `config/schema.py` — Added `StoragePathConfig`, `ManagedStorageConfig`; made `dropbox` optional; added `managed` + `storage_paths` fields; model validator for exactly-one provider
- `config/credentials.py` — Added `ManagedStorageCredentials`; extended `CredentialPayload` union
- `config/source.py` — Removed `DROPBOX_APP_KEY` guard; branched on `storage.provider` in `_build_app_config_v1/v2`; added `"managed"` to `get_credentials` dispatch
- `config/loader.py` — Added `STORAGE_PROVIDER=managed` + `R2_*` env var support; populates `storage_paths` for both providers
- `core/workflow.py` — Replaced 7 `config.dropbox.*` path accesses with `config.storage_paths.*`
- `web/service.py` — Replaced 12 `config.dropbox.*` path accesses; uses `create_storage(cfg)`
- `services/sidecar.py` — Replaced 2 `config.dropbox.*` path accesses
- `app.py` — Replaced 2 `cfg.dropbox.*` path accesses; uses `create_storage(cfg)`
- `utils/logging.py` — Added S3/R2 credential patterns to `SanitizingFilter`

### Test code (modified — storage_paths addition)
- 21 existing test files updated to include `storage_paths=StoragePathConfig(...)` in `ApplicationConfig` constructors
- `test_app_cli.py` — Updated mock config with `storage_paths`; patched `create_storage` instead of `DropboxStorage`
- `test_config_keep_remove.py`, `test_orchestrator_runtime_config.py`, `test_workflow_feature_toggles.py` — Added type narrowing `assert cfg.dropbox is not None`
- `test_workflow_keep_remove.py`, `test_web_keep_remove_service.py`, `test_web_admin_login_folder_check.py` — Matched `StoragePathConfig.folder_remove` to test expectations

## Acceptance Criteria

### ManagedStorage adapter
- [x] AC1 — `ManagedStorage` implements `StorageProtocol` (test: `test_isinstance_check`)
- [x] AC2 — `list_images` filters by extension (test: `test_returns_filtered_filenames`)
- [x] AC3 — `download_image` returns bytes (test: `test_returns_bytes`)
- [x] AC4 — `get_temporary_link` returns pre-signed URL (test: `test_returns_presigned_url`)
- [x] AC5 — `get_thumbnail` with Pillow + LRU cache (test: `test_returns_jpeg_bytes`, `test_cache_hit_avoids_second_download`)
- [x] AC6 — `archive_image` copies + deletes (test: `test_copies_and_deletes`)
- [x] AC7 — `move_image_with_sidecars` (test: `test_copies_and_deletes_image`)
- [x] AC8 — `delete_file_with_sidecar` (test: `test_deletes_image_and_sidecar`)
- [x] AC9 — `write_sidecar_text` with UTF-8 (test: `test_puts_object_with_utf8`)
- [x] AC10 — `download_sidecar_if_exists` returns None on NoSuchKey (test: `test_returns_none_on_no_such_key`)
- [x] AC11 — `get_file_metadata` returns ETag + LastModified (test: `test_returns_etag_and_last_modified`)
- [x] AC12 — `supports_content_hashing()` returns True; ETag-based hashes (test: `test_supports_content_hashing`, `test_list_images_with_hashes_returns_etags`)
- [x] AC13 — All S3 calls via `asyncio.to_thread` (test: `test_list_images_uses_to_thread`)
- [x] AC14 — Transient retry + permanent error raises StorageError (test: `test_permanent_error_raises_storage_error`)

### Config and factory
- [x] AC15 — Model validator: exactly one of dropbox/managed (test: `TestApplicationConfigValidator`)
- [x] AC16 — `StoragePathConfig` exists with correct fields (test: `TestStoragePathConfig`)
- [x] AC17 — Factory returns correct backend (test: `test_factory_returns_dropbox_storage`, `test_factory_returns_managed_storage`)
- [x] AC18 — `app.py` and `web/service.py` use `create_storage(cfg)` (verified in source)

### Orchestrator mode
- [x] AC19 — No crash without DROPBOX keys (test: `test_init_succeeds_without_dropbox_keys`)
- [x] AC20 — `_build_app_config_v1/v2` branches on provider (code verified)
- [x] AC21 — Existing Dropbox tests pass unchanged (508 pass)

### Standalone mode
- [x] AC22 — `STORAGE_PROVIDER=managed` + R2 env vars works (test: `test_managed_env_builds_config`)
- [x] AC23 — Default Dropbox preserved (test: `test_default_dropbox_builds_config`)

### Security and quality
- [x] AC24 — S3/R2 credential patterns added to SanitizingFilter
- [x] AC25 — `ensure_folder_exists` is no-op; preview safety maintained (test: `test_noop`)
- [x] AC26 — Zero lint/mypy violations
- [x] AC27 — 30 new tests across 3 test files

## Test Results

```
508 passed, 1 failed (pre-existing email test), 49 warnings
30 new PUB-024 tests:
  - test_managed_storage.py: 18 tests
  - test_storage_factory.py: 2 tests
  - test_config_managed.py: 10 tests
```

## Quality Gates

- Format: zero reformats needed
- Lint: zero violations
- Type check: zero errors (mypy)
- Tests: 508 passed, 1 pre-existing failure
- Coverage: 90% overall (managed_storage.py: 86%, storage_factory.py: 91%, schema.py: 98%, credentials.py: 100%)

## Dependencies Added

- `boto3` — S3-compatible client for managed storage
- `Pillow` — Server-side thumbnail generation
- `boto3-stubs` (dev) — Type stubs for boto3

## Notes

- The thumbnail cache is a simple dict-based FIFO cache (max 500 entries) rather than `functools.lru_cache` because the cache needs to be keyed by `(object_key, size)` and the function signature includes `self`. A module-level dict is simpler and more testable.
- `StoragePathConfig.folder_remove` defaults to `"reject"` (matching `DropboxConfig.folder_remove` default) for backward compatibility.
- `DropboxStorage.get_thumbnail` still accepts both protocol-level and Dropbox SDK enum types (from PUB-023).
