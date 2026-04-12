# PUB-024: Managed Storage Adapter

| Field | Value |
|-------|-------|
| **ID** | PUB-024 |
| **Category** | Storage |
| **Priority** | P1 |
| **Effort** | M |
| **Status** | Not Started |
| **Dependencies** | PUB-023 |

## Problem

Every publisher instance requires users to have a Dropbox account and configure OAuth credentials. This creates onboarding friction and couples the product to a single third-party storage provider. Users who upload photos via the orchestrator's web UI (on `org.shibari.photo`) have no way to use that managed storage — the publisher only speaks Dropbox.

The orchestrator already emits `storage.provider: "managed"` for managed instances (verified live on `cloud-stage.shibari.photo`) and resolves R2 credentials via `/v1/credentials/resolve`. The publisher currently crashes on `provider != "dropbox"`.

## Desired Outcome

A `ManagedStorage` adapter implementing `StorageProtocol` (from PUB-023) that reads from S3-compatible object storage. Instances configured with `provider: "managed"` use this adapter instead of Dropbox. From the publisher's perspective — workflow, web service, AI analysis, curation — the behavior is identical. Images are uploaded to managed storage externally (by the orchestrator); the publisher only consumes them.

## Scope

### Part A: `ManagedStorage` adapter (`services/managed_storage.py`)

- Implement `ManagedStorage` class satisfying `StorageProtocol`
- S3-compatible backend via `boto3` (targeting Cloudflare R2; works with AWS S3, MinIO)
- All protocol methods:
  - `list_images` — list objects by prefix, filter image extensions
  - `list_images_with_hashes` — return `(filename, ETag)` tuples
  - `download_image` — `get_object` → bytes
  - `get_temporary_link` — `generate_presigned_url` with configurable expiry (default 1h)
  - `get_thumbnail` — download + Pillow resize + LRU cache (in-memory, keyed by `(key, size)`)
  - `get_file_metadata` — return `ETag` and `LastModified`
  - `write_sidecar_text` — `put_object` with `.txt` key
  - `download_sidecar_if_exists` — `get_object`, return `None` on `NoSuchKey`
  - `archive_image` — `copy_object` + `delete_object` for image + sidecar
  - `move_image_with_sidecars` — same copy+delete pattern
  - `delete_file_with_sidecar` — `delete_object` for image + sidecar
  - `ensure_folder_exists` — no-op (S3 has no real folders)
  - `supports_content_hashing` — returns `True` (ETag-based)
- All `boto3` calls wrapped in `asyncio.to_thread`
- Retry with exponential backoff (tenacity) on transient S3 errors
- `StorageError` raised for all S3 failures

### Part B: Storage-agnostic path config (`StoragePathConfig`)

`config.dropbox.image_folder`, `config.dropbox.archive_folder`, `config.dropbox.folder_keep`, `config.dropbox.folder_remove` are accessed in **26 places** across `workflow.py`, `web/service.py`, `sidecar.py`, `app.py`. These must become provider-agnostic.

- New `StoragePathConfig` model in `config/schema.py`:
  ```
  class StoragePathConfig(BaseModel):
      image_folder: str       # root path (Dropbox: "/My Photos", managed: "tenant/instance")
      archive_folder: str     # archive path
      folder_keep: str | None # keep subfolder
      folder_remove: str | None # remove subfolder
  ```
- `ApplicationConfig` gains `storage_paths: StoragePathConfig` (always set, regardless of provider)
- All 26 `config.dropbox.*` path accesses change to `config.storage_paths.*`
- `DropboxConfig` validation (`must start with /`) stays on `DropboxConfig.image_folder`; `StoragePathConfig` has no such constraint (managed paths are relative)
- Config builders (`source.py`, `loader.py`) populate `storage_paths` from the appropriate source

### Part C: `ManagedStorageConfig` and schema migration

- New `ManagedStorageConfig` in `config/schema.py`:
  ```
  class ManagedStorageConfig(BaseModel):
      access_key_id: str
      secret_access_key: str
      endpoint_url: str
      bucket: str
      region: str = "auto"
  ```
- `ApplicationConfig.dropbox` changes from required to `DropboxConfig | None = None`
- `ApplicationConfig.managed` added as `ManagedStorageConfig | None = None`
- Model validator: exactly one of `dropbox` or `managed` must be set

### Part D: Config source changes (`source.py`)

- `OrchestratorConfigSource.__init__`: remove the unconditional `DROPBOX_APP_KEY`/`DROPBOX_APP_SECRET` guard; defer to Dropbox config construction
- `_build_app_config_v1` / `_build_app_config_v2`: branch on `storage.provider`:
  - `"dropbox"`: current path (resolve `DropboxCredentials`, build `DropboxConfig`, require `DROPBOX_APP_KEY`/`DROPBOX_APP_SECRET`)
  - `"managed"`: resolve `ManagedStorageCredentials`, build `ManagedStorageConfig`
- `get_credentials`: add `provider == "managed"` → `ManagedStorageCredentials.model_validate(data)` branch

### Part E: Credential model (`credentials.py`)

- New `ManagedStorageCredentials`:
  ```
  class ManagedStorageCredentials(BaseModel):
      provider: Literal["managed"]
      version: str
      access_key_id: str
      secret_access_key: str
      endpoint_url: str
      bucket: str
      region: str
  ```
- Add to `CredentialPayload` union

### Part F: Storage factory

- New `create_storage()` function (in `services/storage_factory.py` or similar):
  ```
  def create_storage(config: ApplicationConfig) -> StorageProtocol
  ```
  - Returns `DropboxStorage(config.dropbox)` when `config.dropbox` is set
  - Returns `ManagedStorage(config.managed)` when `config.managed` is set
- Replace `DropboxStorage(cfg.dropbox)` in `app.py` (line 51) and `web/service.py` (line 73) with `create_storage(cfg)`

### Part G: Standalone config (`loader.py`)

- Support `STORAGE_PROVIDER=managed` env var (default: `dropbox`)
- When `managed`: read `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`, `R2_BUCKET_NAME`, `R2_REGION` from env; build `ManagedStorageConfig`
- `STORAGE_PATHS` env var works for both providers (paths are provider-agnostic)
- When `dropbox`: existing behavior unchanged

## Non-Goals

- No admin bulk upload or Dropbox → managed migration (PUB-031)
- No CDN or edge caching layer
- Orchestrator contract work is tracked in the orchestrator repo (issue #95, already closed/implemented)

## Acceptance Criteria

### ManagedStorage adapter
- AC1: `ManagedStorage` implements `StorageProtocol` and passes mypy type checking
- AC2: `list_images` returns image filenames (`.jpg`, `.jpeg`, `.png`) from the configured S3 prefix
- AC3: `download_image` returns image bytes from S3 via `get_object`
- AC4: `get_temporary_link` returns a pre-signed URL with configurable expiry (default 1 hour)
- AC5: `get_thumbnail` generates a server-side JPEG thumbnail using Pillow; thumbnails are cached in-memory (LRU) to avoid re-downloading/resizing
- AC6: `archive_image` copies image + sidecar to archive prefix, then deletes originals (copy+delete pattern)
- AC7: `move_image_with_sidecars` moves image + sidecar to target subfolder prefix
- AC8: `delete_file_with_sidecar` deletes image + `.txt` sidecar from S3
- AC9: `write_sidecar_text` writes a `.txt` sidecar object alongside the image
- AC10: `download_sidecar_if_exists` returns `None` (not an error) when sidecar key does not exist (`NoSuchKey`)
- AC11: `get_file_metadata` returns `ETag` and `LastModified` as string dict values
- AC12: `supports_content_hashing()` returns `True`; `list_images_with_hashes` returns `(filename, ETag)` tuples
- AC13: All S3 operations use `asyncio.to_thread` for non-blocking execution
- AC14: Transient S3 errors (5xx, `ConnectionError`, `EndpointConnectionError`) are retried with exponential backoff (3 attempts)

### Config and factory
- AC15: `ApplicationConfig.dropbox` is `DropboxConfig | None` (was required); `ApplicationConfig.managed` is `ManagedStorageConfig | None`; model validator enforces exactly one is set
- AC16: `StoragePathConfig` exists; all 26 `config.dropbox.*` path accesses are replaced with `config.storage_paths.*`
- AC17: Storage factory `create_storage(config)` returns `DropboxStorage` for Dropbox config, `ManagedStorage` for managed config
- AC18: `app.py` and `web/service.py` use `create_storage(cfg)` instead of `DropboxStorage(cfg.dropbox)`

### Orchestrator mode
- AC19: `OrchestratorConfigSource.__init__` no longer crashes without `DROPBOX_APP_KEY`/`DROPBOX_APP_SECRET` when no Dropbox tenants are served
- AC20: `_build_app_config_v1/v2` builds `ManagedStorageConfig` when `storage.provider == "managed"`, resolving credentials via `ManagedStorageCredentials`
- AC21: Existing Dropbox-backed tenants work identically (no regression) — `provider: "dropbox"` still requires `DROPBOX_APP_KEY`/`DROPBOX_APP_SECRET` and builds `DropboxConfig`

### Standalone mode
- AC22: `STORAGE_PROVIDER=managed` with `R2_*` env vars builds `ManagedStorageConfig` and `ManagedStorage`
- AC23: Default `STORAGE_PROVIDER=dropbox` (or unset) preserves existing Dropbox behavior exactly

### Security and logging
- AC24: No credentials (`access_key_id`, `secret_access_key`, `endpoint_url`) appear in logs — `SanitizingFilter` updated if needed
- AC25: Preview mode with managed storage is side-effect free (no S3 writes)

### Quality
- AC26: Zero new lint (`ruff check`) or type-check (`mypy`) violations
- AC27: Tests cover: `ManagedStorage` protocol compliance, each protocol method, factory dispatch, config parsing for both providers, credential resolution for managed, standalone env loading, backward compatibility with Dropbox

## Implementation Notes

- Use `boto3` for S3 compatibility — works with R2, S3, MinIO via `endpoint_url`
- Pre-signed URLs: `client.generate_presigned_url('get_object', Params={'Bucket': ..., 'Key': ...}, ExpiresIn=3600)`
- Thumbnail cache: `functools.lru_cache` or `cachetools.LRUCache` keyed by `(object_key, size_value)` — limit 500 entries
- Object key layout matches orchestrator projection: `{tenant_slug}/{instance_name}/{filename}` with `archive/`, `keep/`, `remove/` under root
- `ensure_folder_exists` is a no-op for S3 — return immediately
- `_is_sidecar_not_found_error` equivalent: catch `ClientError` with code `NoSuchKey` or `404`
- Credential shape from orchestrator (verified live): `{ "provider": "managed", "version": "...", "access_key_id": "...", "secret_access_key": "...", "endpoint_url": "...", "bucket": "publisher-media", "region": "auto" }`
- R2 credentials are served from orchestrator env vars, NOT stored per-tenant — all managed instances share the same R2 bucket with different key prefixes

### Dependency: `boto3`

Add `boto3` to project dependencies: `uv add boto3` (+ `boto3-stubs` for type checking if desired)

### Dependency: `Pillow`

Add `Pillow` to project dependencies for server-side thumbnail generation: `uv add Pillow`

## Related

- [PUB-023: Storage Protocol Extraction](PUB-023_storage-protocol-extraction.md) — prerequisite; defines the protocol this adapter implements
- [PUB-031: Managed Storage Migration & Admin Library](PUB-031_managed-storage-migration-admin-library.md) — migration + admin library
- [PUB-015: Cloud Storage Adapter (Dropbox)](archive/PUB-015_cloud-storage-dropbox.md) — the existing adapter
- Orchestrator issue #95 (closed) — orchestrator-side managed storage support

---

*2026-03-16 — Spec hardened for Claude Code handoff*
