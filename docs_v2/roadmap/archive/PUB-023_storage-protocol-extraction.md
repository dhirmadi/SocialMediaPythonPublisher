# PUB-023: Storage Protocol Extraction

| Field | Value |
|-------|-------|
| **ID** | PUB-023 |
| **Category** | Foundation |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Done |
| **Dependencies** | PUB-015 |

## Problem

The publisher's storage contract is implicit. `DropboxStorage` is the only implementation, and all consumers (`WorkflowOrchestrator`, `WebImageService`, `generate_and_upload_sidecar`) type-hint it concretely. There is no formal `Protocol` or base class — the interface is defined only by convention and test dummies. This makes it impossible to introduce a second storage backend without touching every consumer, and it increases the risk of interface drift.

## Desired Outcome

A formal `StorageProtocol` (Python `Protocol` class) that captures the methods the publisher consumes. All consumers type-hint the protocol instead of `DropboxStorage`. `DropboxStorage` implements the protocol. No behavior change — this is a pure refactor that establishes the extension point for alternative storage backends (PUB-024).

## Scope

### Production code

- Define `StorageProtocol` in a new `publisher_v2/services/storage_protocol.py` with all methods consumed by workflow, web service, and sidecar utilities
- Define protocol-level thumbnail types (`ThumbnailSize` and `ThumbnailFormat` as `StrEnum`) in the protocol module, replacing Dropbox SDK enums in the public interface
- Replace `DropboxStorage` type hints with `StorageProtocol` in:
  - `publisher_v2/core/workflow.py` — `WorkflowOrchestrator.__init__(storage: StorageProtocol)`
  - `publisher_v2/services/sidecar.py` — `generate_and_upload_sidecar(storage: StorageProtocol)`
  - `publisher_v2/web/service.py` — `self.storage` attribute type
- Replace the `hasattr`/`getattr` pattern for `list_images_with_hashes` + `client` (workflow.py lines 63-66) with a protocol method `supports_content_hashing() -> bool`
- `DropboxStorage.get_thumbnail` maps protocol-level `ThumbnailSize`/`ThumbnailFormat` to Dropbox SDK enums internally
- `web/service.py` imports protocol-level thumbnail enums instead of `from dropbox.files import ThumbnailSize`

### Instantiation sites (unchanged)

- `app.py` and `web/service.py` still instantiate `DropboxStorage(cfg.dropbox)` directly — no factory yet (that is PUB-024)

### Config access pattern (unchanged)

- `config.dropbox.image_folder` / `archive_folder` / `folder_keep` / `folder_remove` access remains — decoupling config from storage is PUB-024's concern

### Test code

- Update `BaseDummyStorage` in `tests/conftest.py` to implement `StorageProtocol` (add missing methods: `get_thumbnail`, `ensure_folder_exists`, `delete_file_with_sidecar`, `list_images_with_hashes`, `supports_content_hashing`)
- Replace `_DummyStorage(DropboxStorage)` subclasses in `test_publisher_async_throughput.py` and `test_e2e_performance_telemetry.py` with `_DummyStorage(BaseDummyStorage)` (no longer inherit from concrete class)
- Tests that construct real `DropboxStorage` instances for unit testing Dropbox-specific behavior (`test_storage_thumbnail.py`, `test_dropbox_storage_service.py`, `test_storage_error_paths.py`, `test_dropbox_sidecar.py`, etc.) remain unchanged — they test the concrete implementation

## Non-Goals

- No new storage backend (that is PUB-024)
- No config changes — storage selection remains Dropbox-only; no factory pattern yet
- No behavior change — all existing tests must pass unchanged
- No decoupling of `config.dropbox.*` path access — that moves with the storage factory in PUB-024

## Acceptance Criteria

- AC1: A `StorageProtocol` class exists in `publisher_v2/services/storage_protocol.py` defining all 14 public methods consumed by workflow, web service, and sidecar utilities
- AC2: `WorkflowOrchestrator.__init__`, `generate_and_upload_sidecar`, and `WebImageService` use `StorageProtocol` in their type signatures (not `DropboxStorage`)
- AC3: `DropboxStorage` satisfies `StorageProtocol` as verified by mypy (structural subtyping, no explicit inheritance required)
- AC4: Protocol-level `ThumbnailSize` and `ThumbnailFormat` are defined as `StrEnum` in `storage_protocol.py`; `DropboxStorage.get_thumbnail` maps these to Dropbox SDK enums internally; `web/service.py` imports from `storage_protocol` not `dropbox.files`
- AC5: The `hasattr(self.storage, "list_images_with_hashes") and getattr(self.storage, "client", None)` pattern in `workflow.py` is replaced by `self.storage.supports_content_hashing()`, a protocol method returning `bool`
- AC6: `BaseDummyStorage` in `tests/conftest.py` implements `StorageProtocol` (all required methods present with correct signatures)
- AC7: `_DummyStorage` classes in `test_publisher_async_throughput.py` and `test_e2e_performance_telemetry.py` no longer subclass `DropboxStorage`
- AC8: All existing tests pass without modification to test logic or assertions (only import/type changes)
- AC9: Zero new lint (`ruff check`) or type-check (`mypy`) violations in changed files

## Implementation Notes

- Use `typing.Protocol` with `@runtime_checkable` so `isinstance` checks are possible if needed
- `supports_content_hashing()` returns `True` in `DropboxStorage` (has `list_images_with_hashes` and real client), `False` in `BaseDummyStorage` by default
- `_is_sidecar_not_found_error` is a Dropbox-specific static method — it stays on `DropboxStorage` only, not in the protocol
- `StorageError` remains the common exception type across all implementations
- Keep the protocol module separate from `storage.py` to avoid circular imports (protocol has no Dropbox dependency)
- The protocol's `ThumbnailSize` enum values should use the same string keys as the web API's `ThumbnailSizeParam` (`w32h32`, `w64h64`, ..., `w960h640`)

## Related

- [PUB-015: Cloud Storage Adapter (Dropbox)](archive/PUB-015_cloud-storage-dropbox.md) — the current Dropbox implementation
- [PUB-024: Managed Storage Adapter](PUB-024_managed-storage-adapter.md) — the follow-on item this unblocks

---

*2026-03-16 — Spec hardened for Claude Code handoff*
