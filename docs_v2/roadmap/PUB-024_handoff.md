# Implementation Handoff: PUB-024 — Managed Storage Adapter

**Hardened:** 2026-03-16
**Status:** Ready for implementation

## For Claude Code

Read `docs_v2/roadmap/PUB-024_managed-storage-adapter.md` first — it is the spec.

**Prerequisite:** PUB-023 (Storage Protocol Extraction) must be implemented first. This item builds on `StorageProtocol`.

This item has 7 parts (A–G). Suggested implementation order: E → C → B → D → G → A → F (credentials → schema → paths → config source → standalone → adapter → factory/wiring).

### Test-first targets

| AC | Test file | Key test cases |
|----|-----------|----------------|
| AC1 | `tests/test_managed_storage.py` (new) | `isinstance(ManagedStorage(...), StorageProtocol)` with mocked boto3 |
| AC2 | `tests/test_managed_storage.py` | `list_images` returns filtered filenames from mocked `list_objects_v2` |
| AC3 | `tests/test_managed_storage.py` | `download_image` returns bytes from mocked `get_object` |
| AC4 | `tests/test_managed_storage.py` | `get_temporary_link` returns a string URL from mocked `generate_presigned_url` |
| AC5 | `tests/test_managed_storage.py` | `get_thumbnail` returns JPEG bytes; second call hits cache (no second download) |
| AC6 | `tests/test_managed_storage.py` | `archive_image` calls `copy_object` + `delete_object` for image + sidecar |
| AC7 | `tests/test_managed_storage.py` | `move_image_with_sidecars` copies + deletes image + sidecar |
| AC8 | `tests/test_managed_storage.py` | `delete_file_with_sidecar` calls `delete_object` for image + `.txt` sidecar |
| AC9 | `tests/test_managed_storage.py` | `write_sidecar_text` calls `put_object` with correct key and UTF-8 bytes |
| AC10 | `tests/test_managed_storage.py` | `download_sidecar_if_exists` returns `None` on `NoSuchKey` error |
| AC11 | `tests/test_managed_storage.py` | `get_file_metadata` returns dict with `ETag` and `LastModified` keys |
| AC12 | `tests/test_managed_storage.py` | `supports_content_hashing()` returns `True`; `list_images_with_hashes` returns `(name, etag)` |
| AC13 | `tests/test_managed_storage.py` | All methods wrap boto3 calls in `asyncio.to_thread` (verify via mock) |
| AC14 | `tests/test_managed_storage.py` | Transient errors trigger retry; permanent errors raise `StorageError` |
| AC15 | `tests/test_config_managed.py` (new) | `ApplicationConfig(dropbox=None, managed=m, ...)` validates; `ApplicationConfig(dropbox=d, managed=m, ...)` fails; `ApplicationConfig(dropbox=None, managed=None, ...)` fails |
| AC16 | `tests/test_config_managed.py` | `StoragePathConfig` model exists; fields match `image_folder`, `archive_folder`, `folder_keep`, `folder_remove` |
| AC17 | `tests/test_storage_factory.py` (new) | `create_storage(config_with_dropbox)` returns `DropboxStorage`; `create_storage(config_with_managed)` returns `ManagedStorage` |
| AC18 | Verified by integration | `app.py` and `web/service.py` use `create_storage` |
| AC19 | `tests/test_config_managed.py` | `OrchestratorConfigSource()` succeeds without `DROPBOX_APP_KEY` when env has `ORCHESTRATOR_BASE_URL` and `ORCHESTRATOR_SERVICE_TOKEN` |
| AC20 | `tests/test_config_managed.py` | `_build_app_config_v2` with `provider: "managed"` builds `ManagedStorageConfig` + `StoragePathConfig` |
| AC21 | Existing orchestrator config tests | All existing Dropbox-backed config tests pass unchanged |
| AC22 | `tests/test_config_managed.py` | Standalone `load_application_config` with `STORAGE_PROVIDER=managed` + `R2_*` env vars builds correct config |
| AC23 | Existing loader tests | Existing standalone tests pass unchanged (default Dropbox) |
| AC24 | `tests/test_config_managed.py` | `ManagedStorageConfig` fields don't appear in sanitized log output |
| AC25 | `tests/test_managed_storage.py` | Preview mode: verify no S3 write operations are called |
| AC26 | Quality gates | `uv run ruff check` + `uv run mypy` — zero violations |
| AC27 | All test files above | Comprehensive coverage across adapter, factory, config, credentials |

### Mock boundaries

| External service | Mock strategy | Notes |
|-----------------|---------------|-------|
| boto3 S3 client | `unittest.mock.patch('boto3.client')` returning `MagicMock` | All S3 operations are on the client; mock individual methods (`list_objects_v2`, `get_object`, `put_object`, `copy_object`, `delete_object`, `generate_presigned_url`, `head_object`) |
| Pillow (PIL) | No mock needed | Used for real thumbnail generation in tests; small test images |
| Orchestrator API | `unittest.mock.AsyncMock` on `OrchestratorClient` | For credential resolution tests |
| Dropbox SDK | Existing mocks unchanged | Dropbox tests not affected |

### Files to create

| File | Purpose |
|------|---------|
| `publisher_v2/src/publisher_v2/services/managed_storage.py` | `ManagedStorage` class implementing `StorageProtocol` |
| `publisher_v2/src/publisher_v2/services/storage_factory.py` | `create_storage(config) -> StorageProtocol` factory |
| `publisher_v2/tests/test_managed_storage.py` | ManagedStorage unit tests |
| `publisher_v2/tests/test_storage_factory.py` | Factory dispatch tests |
| `publisher_v2/tests/test_config_managed.py` | Config/credential/standalone tests for managed provider |

### Files to modify

| File | Changes |
|------|---------|
| `config/schema.py` | Add `ManagedStorageConfig`, `StoragePathConfig`; make `dropbox` optional; add `managed` + `storage_paths`; add model validator |
| `config/credentials.py` | Add `ManagedStorageCredentials`; extend `CredentialPayload` union |
| `config/source.py` | Remove startup guard; branch on `storage.provider` in `_build_app_config_v1/v2`; add `"managed"` to `get_credentials` dispatch |
| `config/loader.py` | Support `STORAGE_PROVIDER=managed` + `R2_*` env vars; populate `storage_paths` |
| `core/workflow.py` | Replace all `self.config.dropbox.*` path accesses (7 locations) with `self.config.storage_paths.*` |
| `web/service.py` | Replace all `self.config.dropbox.*` path accesses (12 locations) with `self.config.storage_paths.*`; use `create_storage(cfg)` at line 73 |
| `services/sidecar.py` | Replace `config.dropbox.image_folder` (2 locations) with `config.storage_paths.image_folder` |
| `app.py` | Replace `cfg.dropbox.*` path accesses (2 locations); use `create_storage(cfg)` at line 51 |
| `utils/logging.py` | Add `access_key_id`, `secret_access_key`, `endpoint_url` to `SanitizingFilter` patterns if not already covered |

### Files NOT to modify

- `services/storage.py` (`DropboxStorage`) — no changes; it already satisfies `StorageProtocol` from PUB-023
- `services/storage_protocol.py` — no changes; protocol is complete from PUB-023
- Dropbox-specific test files (`test_dropbox_*.py`, `test_storage_*.py`) — unchanged
- `services/tenant_factory.py` — no changes needed (WebImageService handles storage internally)

### `config.dropbox.*` → `config.storage_paths.*` replacement map

All 26 occurrences across 4 files:

| File | Count | Patterns |
|------|-------|----------|
| `core/workflow.py` | 7 | `config.dropbox.image_folder` (×4), `config.dropbox.archive_folder` (×1), `config.dropbox.folder_keep` (×1), `config.dropbox.folder_remove` (×1) |
| `web/service.py` | 12 | `config.dropbox.image_folder` (×8), `config.dropbox.folder_keep` (×2), `config.dropbox.folder_remove` (×2) |
| `services/sidecar.py` | 2 | `config.dropbox.image_folder` (×2) |
| `app.py` | 2 | `cfg.dropbox.image_folder` (×2) |

All become `config.storage_paths.*` / `cfg.storage_paths.*`.

### Orchestrator credential response (verified live)

```json
{
  "provider": "managed",
  "version": "98f957...",
  "access_key_id": "03ae658a...",
  "secret_access_key": "e6bbe6...",
  "endpoint_url": "https://c448850aa6bf817e31e2963d213a0c12.r2.cloudflarestorage.com",
  "bucket": "publisher-media",
  "region": "auto"
}
```

### Orchestrator runtime paths (verified live for `cloud-stage.shibari.photo`)

```json
{
  "storage": {
    "provider": "managed",
    "credentials_ref": "014a7ae1...",
    "paths": {
      "root": "cloud-stage/cloud-stage",
      "archive": "cloud-stage/cloud-stage/archive",
      "keep": "cloud-stage/cloud-stage/keep",
      "remove": "cloud-stage/cloud-stage/remove"
    }
  }
}
```

### New dependencies

```bash
uv add boto3
uv add Pillow
uv add --group dev boto3-stubs
```

### Non-negotiables for this item

- [ ] **Backward compatibility**: all existing Dropbox-backed flows pass unchanged
- [ ] **Preview mode**: side-effect free with managed storage (no S3 writes)
- [ ] **Secrets**: no `access_key_id`, `secret_access_key`, or `endpoint_url` in logs
- [ ] **Coverage**: ≥80% on all new modules (`managed_storage.py`, `storage_factory.py`, config changes)
- [ ] **Quality gates**: `uv run ruff check` + `uv run mypy` clean

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-024_managed-storage-adapter.md
```
