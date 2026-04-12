# Implementation Handoff: PUB-023 — Storage Protocol Extraction

**Hardened:** 2026-03-16
**Status:** Ready for implementation

## For Claude Code

Read `docs_v2/roadmap/PUB-023_storage-protocol-extraction.md` first — it is the spec.

This is a **pure refactor** with zero behavior change. The goal is to extract an implicit interface into a formal `typing.Protocol` so a second storage backend can be added in PUB-024.

### Test-first targets

| AC | Test file | Key test cases |
|----|-----------|----------------|
| AC1 | `tests/test_storage_protocol.py` (new) | Protocol class exists; defines all 14 public methods; `@runtime_checkable` |
| AC3 | `tests/test_storage_protocol.py` (new) | `assert isinstance(DropboxStorage(...), StorageProtocol)` with mock config |
| AC4 | `tests/test_storage_protocol.py` (new) | Protocol `ThumbnailSize` and `ThumbnailFormat` are `StrEnum`; all expected values present; `DropboxStorage.get_thumbnail` accepts protocol enums |
| AC5 | `tests/test_storage_protocol.py` (new) | `DropboxStorage.supports_content_hashing()` returns `True`; `BaseDummyStorage.supports_content_hashing()` returns `False` |
| AC2 | Verified by mypy | `WorkflowOrchestrator`, `generate_and_upload_sidecar`, `WebImageService` accept `StorageProtocol` — mypy pass is the test |
| AC6 | `tests/test_storage_protocol.py` (new) | `assert isinstance(BaseDummyStorage(), StorageProtocol)` |
| AC7 | Verified by inspection | `_DummyStorage` in two test files no longer inherits `DropboxStorage` |
| AC8 | All existing test files | `uv run pytest -v` — full suite passes, no test logic changes |
| AC9 | N/A | `uv run ruff check` + `uv run mypy` — zero violations in changed files |

### Protocol method inventory (all 14 + 1 capability method)

These are the methods `StorageProtocol` must define, derived from production usage:

```python
from typing import Protocol, runtime_checkable
from publisher_v2.services.storage_protocol import ThumbnailSize, ThumbnailFormat

@runtime_checkable
class StorageProtocol(Protocol):
    async def list_images(self, folder: str) -> list[str]: ...
    async def list_images_with_hashes(self, folder: str) -> list[tuple[str, str]]: ...
    async def download_image(self, folder: str, filename: str) -> bytes: ...
    async def get_temporary_link(self, folder: str, filename: str) -> str: ...
    async def get_file_metadata(self, folder: str, filename: str) -> dict[str, str]: ...
    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None: ...
    async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None: ...
    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None: ...
    async def move_image_with_sidecars(self, folder: str, filename: str, target_subfolder: str) -> None: ...
    async def delete_file_with_sidecar(self, folder: str, filename: str) -> None: ...
    async def ensure_folder_exists(self, folder_path: str) -> None: ...
    async def get_thumbnail(self, folder: str, filename: str, size: ThumbnailSize = ThumbnailSize.W960H640, format: ThumbnailFormat = ThumbnailFormat.JPEG) -> bytes: ...
    def supports_content_hashing(self) -> bool: ...
```

### Mock boundaries

| External service | Mock strategy | Existing fixture |
|-----------------|---------------|------------------|
| Dropbox SDK | Not mocked for protocol tests — only for DropboxStorage-specific tests | `tests/conftest.py::BaseDummyClient` |
| No external services needed | Protocol tests use `BaseDummyStorage` | `tests/conftest.py::dummy_storage` |

### Files to modify

| Area | Files to modify | Purpose |
|------|-----------------|---------|
| **New** | `publisher_v2/src/publisher_v2/services/storage_protocol.py` | `StorageProtocol`, `ThumbnailSize`, `ThumbnailFormat` |
| **New** | `publisher_v2/tests/test_storage_protocol.py` | Protocol compliance tests |
| Core | `publisher_v2/src/publisher_v2/core/workflow.py` | Import `StorageProtocol`; change `__init__` type hint; replace `hasattr`/`getattr` with `supports_content_hashing()` |
| Services | `publisher_v2/src/publisher_v2/services/sidecar.py` | Import `StorageProtocol`; change `generate_and_upload_sidecar` type hint |
| Services | `publisher_v2/src/publisher_v2/services/storage.py` | Import protocol enums; add `supports_content_hashing() -> True`; map protocol `ThumbnailSize`/`ThumbnailFormat` to Dropbox SDK enums in `get_thumbnail` |
| Web | `publisher_v2/src/publisher_v2/web/service.py` | Import `StorageProtocol` + protocol enums; remove `from dropbox.files import ThumbnailSize`; update `self.storage` type |
| Tests | `publisher_v2/tests/conftest.py` | Add missing methods to `BaseDummyStorage`: `get_thumbnail`, `ensure_folder_exists`, `delete_file_with_sidecar`, `list_images_with_hashes`, `supports_content_hashing` |
| Tests | `publisher_v2/tests/test_publisher_async_throughput.py` | Change `_DummyStorage(DropboxStorage)` to `_DummyStorage(BaseDummyStorage)` or standalone |
| Tests | `publisher_v2/tests/test_e2e_performance_telemetry.py` | Same as above |

### Files NOT to modify

- `publisher_v2/src/publisher_v2/app.py` — still instantiates `DropboxStorage(cfg.dropbox)` directly (factory is PUB-024)
- `publisher_v2/src/publisher_v2/web/service.py` line 72 — still instantiates `DropboxStorage(cfg.dropbox)` (factory is PUB-024)
- `publisher_v2/tests/test_storage_thumbnail.py` — tests DropboxStorage-specific behavior; keeps importing `DropboxStorage` and Dropbox SDK types
- `publisher_v2/tests/test_dropbox_storage_service.py` — same
- `publisher_v2/tests/test_storage_error_paths.py` — same
- `publisher_v2/tests/test_dropbox_sidecar.py` — same
- `publisher_v2/tests/test_dropbox_keep_remove_move.py` — same
- `publisher_v2/tests/test_archive_with_sidecar.py` — same
- `publisher_v2/tests/test_app_cli.py` — patches `publisher_v2.app.DropboxStorage`; unchanged until factory exists

### Key design decisions (already made)

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Protocol location | New file `storage_protocol.py` | Avoids circular imports; protocol has no Dropbox dependency |
| `list_images_with_hashes` | In protocol (not optional) | All backends should support it; S3 uses ETag, Dropbox uses content_hash |
| Feature detection | `supports_content_hashing() -> bool` method | Replaces fragile `hasattr` + `getattr` duck-typing |
| Thumbnail types | `StrEnum` in protocol module | String keys match web API's `ThumbnailSizeParam`; `DropboxStorage` maps internally |
| `_is_sidecar_not_found_error` | Stays on `DropboxStorage` only | Dropbox-specific error handling, not part of the protocol |
| `@runtime_checkable` | Yes | Enables `isinstance` checks in tests and future factory |
| Inheritance | Not required | `DropboxStorage` satisfies protocol via structural subtyping (duck typing) |

### Non-negotiables for this item

- [ ] **Zero behavior change**: no functional difference before and after; only type signatures and imports change
- [ ] **All existing tests pass**: `uv run pytest -v` — no test logic or assertion changes
- [ ] **Clean quality gates**: `uv run ruff check` + `uv run mypy` — zero new violations
- [ ] **Coverage**: new `test_storage_protocol.py` covers protocol definition and compliance

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-023_storage-protocol-extraction.md
```
