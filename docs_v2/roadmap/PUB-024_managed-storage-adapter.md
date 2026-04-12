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

## Desired Outcome

A `ManagedStorage` adapter implementing `StorageProtocol` (from PUB-023) that reads from S3-compatible object storage. Instances configured with `provider: "managed"` use this adapter instead of Dropbox. From the publisher's perspective — workflow, web service, AI analysis, curation — the behavior is identical. Images are uploaded to managed storage externally (by the orchestrator); the publisher only consumes them.

## Scope

- Implement `ManagedStorage` class satisfying `StorageProtocol`
- S3-compatible backend (targeting Cloudflare R2; works with AWS S3, MinIO)
- All protocol methods: `list_images`, `download_image`, `get_temporary_link` (pre-signed URLs), `get_thumbnail` (server-side generation via Pillow), `archive_image`, `move_image_with_sidecars`, `delete_file_with_sidecar`, `write_sidecar_text`, `download_sidecar_if_exists`, `get_file_metadata`, `ensure_folder_exists`
- Storage factory: instantiate `DropboxStorage` or `ManagedStorage` based on `provider` config
- Config support: `provider: "managed"` in orchestrator `RuntimeStorage` schema and in standalone INI config
- Credential resolution: orchestrator resolves managed storage via existing `/v1/credentials/resolve` with **`provider: "managed"`** and fields **`access_key_id`**, **`secret_access_key`**, **`endpoint_url`**, **`bucket`**, **`region`** (S3-compatible; R2 in production)
- Object key layout must match **orchestrator-projected paths** (e.g. `{tenant_slug}/{instance_name}/…` with `archive` / `keep` / `remove` under root); see orchestrator `project_runtime_config`

## Non-Goals

- No **admin bulk upload** or **Dropbox → managed migration** in this item — those are [PUB-031: Managed Storage Migration & Admin Library](PUB-031_managed-storage-migration-admin-library.md)
- No first-party **orchestrator dashboard** file browser (orchestrator repo); PUB-031 may add Publisher-side admin library or defer uploads to orchestrator per hardening decision
- No CDN or edge caching layer (can be added later)
- Orchestrator contract work is tracked in the orchestrator repo; Publisher assumes **`storage.provider`** of **`dropbox`** or **`managed`** as already emitted by `/v1/runtime/by-host`

## Acceptance Criteria

- AC1: `ManagedStorage` implements `StorageProtocol` and passes mypy type checking
- AC2: `list_images` returns image filenames from the configured S3 prefix/folder
- AC3: `download_image` returns image bytes from S3
- AC4: `get_temporary_link` returns a pre-signed URL with configurable expiry (default 1 hour)
- AC5: `get_thumbnail` generates a server-side thumbnail using Pillow and returns JPEG bytes; thumbnails are cached to avoid regeneration
- AC6: `archive_image` moves the object (copy + delete) to the archive prefix, including sidecars
- AC7: `move_image_with_sidecars` and `delete_file_with_sidecar` work correctly with S3 object keys
- AC8: `write_sidecar_text` writes a `.txt` sidecar object alongside the image
- AC9: `download_sidecar_if_exists` returns `None` (not an error) when no sidecar exists
- AC10: Storage factory selects `ManagedStorage` when `provider: "managed"` and `DropboxStorage` when `provider: "dropbox"`
- AC11: Orchestrator config with `provider: "managed"` is parsed correctly; credentials resolved via `/v1/credentials/resolve`
- AC12: Standalone INI config supports `[Storage]` section with `provider = managed` and S3 connection fields
- AC13: `WorkflowOrchestrator` and `WebImageService` work identically regardless of which storage adapter is injected (no code changes needed in consumers)
- AC14: All S3 operations use `asyncio.to_thread` for non-blocking execution
- AC15: Retry with exponential backoff on transient S3 errors (5xx, connection errors)
- AC16: No credentials (access keys, secrets, endpoints) in logs

## Implementation Notes

- Use `boto3` (or `aioboto3`) for S3 compatibility — works with R2, S3, MinIO out of the box
- Pre-signed URLs: `generate_presigned_url('get_object', ...)` with configurable expiry
- Thumbnails: download image → Pillow resize → cache in-memory (LRU) or as a separate S3 object at a `_thumbs/` prefix
- Object key layout: `{prefix}/{folder}/{filename}` where prefix is tenant-scoped
- `get_file_metadata` can return S3 `ETag` and `LastModified` as metadata fields
- `list_images_with_hashes` can use S3 `ETag` (MD5 for non-multipart uploads) as the hash equivalent
- `ensure_folder_exists` is a no-op for S3 (no real folders), but could create a zero-byte marker if needed
- Credential shape for orchestrator: `{ "access_key_id", "secret_access_key", "endpoint_url", "bucket", "region" }`
- Wrap all `boto3` calls in `asyncio.to_thread` since boto3 is synchronous

### Schema migration (critical)

`ApplicationConfig.dropbox` is currently a **required** field. For managed-only instances there is no Dropbox config. This must change:

```python
class ApplicationConfig(BaseModel):
    dropbox: DropboxConfig | None = None          # was required, now optional
    managed: ManagedStorageConfig | None = None    # new
```

Plus a model validator: exactly one of `dropbox` or `managed` must be set, matching the storage provider. All code that accesses `config.dropbox` must be guarded or routed through the storage factory.

### Orchestrator env (already provisioned)

R2 credentials are already set on `org-staging` and `org-prod`: `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`, `R2_BUCKET_NAME`, `R2_REGION`. The orchestrator needs to serve these via `/v1/credentials/resolve` for `provider: "managed"` (tracked in orchestrator issue #95).

### Startup guard (critical)

`OrchestratorConfigSource.__init__` (line 130) currently **crashes** if `DROPBOX_APP_KEY` / `DROPBOX_APP_SECRET` are missing — even in orchestrator mode, before any tenant is known. This guard must become **conditional on provider** or deferred to when a Dropbox-backed tenant is actually resolved. Otherwise a dyno serving only managed-storage tenants still needs dummy Dropbox env vars.

### Standalone env vars

For standalone (non-orchestrator) use with managed storage, the publisher needs:
- `STORAGE_PROVIDER=managed` (new; default `dropbox` for backward compatibility)
- `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`, `R2_BUCKET_NAME`, `R2_REGION`
- Or equivalent `[Storage]` INI section with `provider = managed`

## Related

- [PUB-023: Storage Protocol Extraction](PUB-023_storage-protocol-extraction.md) — prerequisite; defines the protocol this adapter implements
- [PUB-031: Managed Storage Migration & Admin Library](PUB-031_managed-storage-migration-admin-library.md) — migration + admin library (upload/list/delete)
- [PUB-015: Cloud Storage Adapter (Dropbox)](archive/PUB-015_cloud-storage-dropbox.md) — the existing adapter; this item adds a second implementation
