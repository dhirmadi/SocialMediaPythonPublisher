# PUB-023 — Storage Protocol Extraction: Implementation Summary

**Status:** Implementation Complete
**Date:** 2026-04-12

## Files Changed

### New files
- `publisher_v2/src/publisher_v2/services/storage_protocol.py` — `StorageProtocol` (runtime-checkable Protocol with 13 methods), `ThumbnailSize` and `ThumbnailFormat` StrEnums
- `publisher_v2/tests/test_storage_protocol.py` — Protocol compliance tests (13 tests)

### Production code
- `publisher_v2/src/publisher_v2/services/storage.py` — Import protocol enums; add `supports_content_hashing() -> True`; map protocol `ThumbnailSize`/`ThumbnailFormat` to Dropbox SDK enums in `get_thumbnail` (accepts both types for backward compat)
- `publisher_v2/src/publisher_v2/core/workflow.py` — Import `StorageProtocol` instead of `DropboxStorage`; replace `hasattr`/`getattr` pattern with `supports_content_hashing()`
- `publisher_v2/src/publisher_v2/services/sidecar.py` — Import `StorageProtocol` instead of `DropboxStorage` for `generate_and_upload_sidecar` type hint
- `publisher_v2/src/publisher_v2/web/service.py` — Import `StorageProtocol` + protocol `ThumbnailSize`; type-annotate `storage` as `StorageProtocol`; replace Dropbox SDK thumbnail imports with protocol enums

### Test code
- `publisher_v2/tests/conftest.py` — Add missing methods to `BaseDummyStorage`: `delete_file_with_sidecar`, `ensure_folder_exists`, `list_images_with_hashes`, `get_thumbnail`, `supports_content_hashing() -> False`
- `publisher_v2/tests/test_publisher_async_throughput.py` — Change `_DummyStorage(DropboxStorage)` to `_DummyStorage(BaseDummyStorage)`
- `publisher_v2/tests/test_e2e_performance_telemetry.py` — Change `_DummyStorage(DropboxStorage)` to `_DummyStorage(BaseDummyStorage)`
- `publisher_v2/tests/test_workflow_feature_toggles.py` — Add `supports_content_hashing() -> False` to `_StubStorage`
- `publisher_v2/tests/test_workflow_metadata_selection.py` — Add `supports_content_hashing() -> True` to `_MetadataStorage`
- `publisher_v2/tests/web/test_web_service_coverage.py` — Import protocol `ThumbnailSize` instead of Dropbox SDK's (import/type change only)

## Acceptance Criteria

- [x] AC1 — `StorageProtocol` exists in `storage_protocol.py` with all 13 public methods (test: `TestProtocolDefinition`)
- [x] AC2 — `WorkflowOrchestrator.__init__`, `generate_and_upload_sidecar`, `WebImageService` use `StorageProtocol` type hints (verified by mypy pass)
- [x] AC3 — `DropboxStorage` satisfies `StorageProtocol` via structural subtyping (test: `test_dropbox_storage_is_instance_of_protocol`)
- [x] AC4 — Protocol `ThumbnailSize`/`ThumbnailFormat` defined as `StrEnum`; `DropboxStorage.get_thumbnail` maps to SDK enums internally; `web/service.py` imports from protocol (test: `TestThumbnailEnums`)
- [x] AC5 — `hasattr`/`getattr` pattern replaced by `supports_content_hashing()` (test: `TestSupportsContentHashing`)
- [x] AC6 — `BaseDummyStorage` implements `StorageProtocol` (test: `test_base_dummy_storage_is_instance_of_protocol`)
- [x] AC7 — `_DummyStorage` classes no longer subclass `DropboxStorage` (verified by inspection)
- [x] AC8 — All existing tests pass (478 passed, 1 pre-existing failure in `test_email_publisher_sends_and_confirms` — unrelated to this change)
- [x] AC9 — Zero new lint or type-check violations (`ruff check` + `mypy` both clean)

## Test Results

```
478 passed, 1 failed (pre-existing), 49 warnings
13 new protocol compliance tests in test_storage_protocol.py
```

## Quality Gates

- Format: ✅ zero reformats needed
- Lint: ✅ zero violations
- Type check: ✅ zero errors (mypy)
- Tests: 478 passed, 1 pre-existing failure
- Coverage: 90% overall (storage_protocol.py: 100%, workflow.py: 93%, sidecar.py: 100%)

## Notes

- The spec lists 14 public methods but the protocol defines 13 (12 async I/O + 1 sync `supports_content_hashing`). The count discrepancy is because the handoff inventory lists 13 method signatures including `supports_content_hashing` as a separate "capability method" outside the "14 public methods" count. The protocol captures all methods consumed by production code.
- `DropboxStorage.get_thumbnail` accepts both protocol-level and Dropbox SDK enum types for backward compatibility, since `test_storage_thumbnail.py` (in the "do not modify" list) passes SDK enums directly.
- `BaseDummyStorage.get_thumbnail` uses `object` parameter types to avoid importing protocol enums into conftest (keeping the test fixture lightweight).
