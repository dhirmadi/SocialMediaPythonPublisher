# PUB-031: Managed Storage Migration & Admin Library

| Field | Value |
|-------|-------|
| **ID** | PUB-031 |
| **Category** | Storage / Web UI |
| **Priority** | P1 |
| **Effort** | L |
| **Status** | Done |
| **Dependencies** | PUB-023 (Done), PUB-024 (Done) |

## Problem

Operators with existing Dropbox-backed instances need a safe, repeatable way to migrate content to managed storage (Cloudflare R2). After migration, admins need basic library management (list, upload, delete, move) for images in managed storage via the Publisher web UI. Today there is no migration tooling and no web-based file management.

## Desired Outcome

1. **Migration CLI**: A standalone async tool that copies images + sidecars from Dropbox to managed storage (R2), with dry-run, idempotency, progress reporting, and structured logging. Not part of the normal publish workflow.
2. **Admin library API + UI**: Authenticated admin users can list, upload, delete, and move objects in managed storage via the Publisher web app. Scoped to the instance's managed prefix. Hidden for Dropbox-only instances.
3. **No regressions**: Dropbox-backed instances (`provider: "dropbox"`) continue working identically.

## Scope

### Phase A — Migration CLI (`publisher_v2/tools/migrate_storage.py`)

A standalone CLI tool invoked as `uv run python -m publisher_v2.tools.migrate_storage`. **Not** a subcommand of `app.py` — migration is an operator action, not part of the publish workflow.

**Dual-backend configuration**: `ApplicationConfig` forbids both `dropbox` and `managed` simultaneously. The migration tool constructs **two storage instances** directly:
- **Source**: `DropboxStorage` built from explicit env vars (`MIGRATE_DROPBOX_REFRESH_TOKEN`, `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`) + source path args.
- **Target**: `ManagedStorage` built from explicit env vars (`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`, `R2_BUCKET_NAME`, `R2_REGION`) + target prefix args.

This avoids fighting the `ApplicationConfig` model validator.

**CLI arguments**:
| Arg | Required | Description |
|-----|----------|-------------|
| `--source-folder` | Yes | Dropbox root folder path (e.g. `/My Photos`) |
| `--target-prefix` | Yes | Managed storage key prefix (e.g. `tenant/instance`) |
| `--archive-folder` | No | Dropbox archive folder (copies archive too) |
| `--dry-run` | No | List what would be copied; no writes |
| `--limit N` | No | Copy at most N images (for incremental testing) |
| `--resume` | No | Skip objects where target key exists and ETag matches source `content_hash` |

**Behavior**:
- Lists images from Dropbox source folder (`.jpg`, `.jpeg`, `.png`)
- For each image: downloads from Dropbox, uploads to R2 target prefix preserving filename
- For each image: checks for `.txt` sidecar, copies if present
- Copies images from `archive/`, `keep/`, `remove/` subfolders preserving relative structure
- `--resume` (default on): skips if target key already exists and content matches (ETag vs Dropbox `content_hash`; if mismatch or `content_hash` unavailable, re-copies)
- Structured JSON logging via `log_json` — no secrets in output
- Respects Dropbox rate limits (existing retry in `DropboxStorage`) and S3 rate limits (existing retry in `ManagedStorage`)
- Progress: logs `migration_progress` events every 10 files with `{copied, skipped, errors, total}`
- Errors on individual files are logged and counted, not fatal; summary printed at end

**Not included**:
- Orchestrator cutover (flipping `storage_provider`) — documented in cutover checklist only
- Automatic rollback — documented as manual steps

### Phase B — Admin Library API (`web/routers/library.py`)

New `APIRouter(prefix="/api/library", tags=["library"])` with admin-only endpoints. Only active when the instance uses managed storage (`config.managed is not None`).

**Endpoints**:

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/library/objects` | List objects under instance prefix (paginated) |
| `POST` | `/api/library/upload` | Upload image (multipart form, server-side to S3) |
| `DELETE` | `/api/library/objects/{filename}` | Delete object + sidecar |
| `POST` | `/api/library/objects/{filename}/move` | Move between logical folders |

**`GET /api/library/objects`**:
- Query params: `prefix` (optional subfolder filter: `""`, `archive`, `keep`, `remove`), `cursor` (opaque pagination token), `limit` (default 50, max 200)
- Returns: `{ "objects": [{"key": str, "size": int, "last_modified": str}], "cursor": str | null }`
- Auth: `require_auth` + `require_admin`
- If `config.managed is None`: returns `404` with `{"detail": "Library not available for Dropbox instances"}`

**`POST /api/library/upload`**:
- Multipart form: `file` (UploadFile)
- Validates:
  - MIME type in allowlist: `image/jpeg`, `image/png` (reject with 415)
  - File size ≤ 20 MB (reject with 413; configurable via `LIBRARY_MAX_UPLOAD_MB` env, default 20)
  - Filename sanitized (strip path separators, normalize unicode)
- Uploads to `{storage_paths.image_folder}/{sanitized_filename}` via `ManagedStorage` client (`put_object`)
- Returns: `{ "key": str, "size": int }`
- Auth: `require_auth` + `require_admin`
- Rate limit: max 10 uploads per minute per admin session (429 on exceed; server-side counter)
- No credentials in response body or logs

**`DELETE /api/library/objects/{filename}`**:
- Calls `storage.delete_file_with_sidecar(folder, filename)` (existing protocol method)
- Returns: `{ "deleted": str, "sidecar_deleted": bool }`
- Auth: `require_auth` + `require_admin`
- 404 if file does not exist

**`POST /api/library/objects/{filename}/move`**:
- Body: `{ "target_folder": "keep" | "remove" | "archive" | "root" }`
  - `"root"` = `storage_paths.image_folder`; others map to respective `storage_paths.*` paths
- Calls `storage.move_image_with_sidecars(current_folder, filename, target_folder)`
- Returns: `{ "moved": str, "destination": str }`
- Auth: `require_auth` + `require_admin`
- 400 if target_folder is invalid; 404 if file not found

### Phase C — Admin Library UI (minimal, in `index.html`)

Extend the existing single-page admin template with a library panel. Only visible when:
1. Admin is logged in (existing admin cookie check)
2. Backend reports `library_enabled: true` in `/api/config/features`

**UI elements**:
- **Library tab/panel** in the admin section (consistent with existing dark-red theme)
- **Object list**: paginated table with filename, size, modified date; folder filter dropdown (root/archive/keep/remove)
- **Upload button**: opens file picker, validates client-side (MIME + size), shows progress, calls `POST /api/library/upload`
- **Delete button**: per-object, confirmation dialog, calls `DELETE /api/library/objects/{filename}`
- **Move dropdown**: per-object, target folder selection, calls `POST /api/library/objects/{filename}/move`
- Mobile-responsive (no horizontal scroll on 320–768px)
- No new JS frameworks; vanilla JS consistent with existing patterns

### Phase D — Feature flag and config

- New `FeaturesConfig.library_enabled: bool = Field(default=False)` — controls whether library API routes respond (404 when disabled) and whether UI panel is visible
- Library auto-enabled when `config.managed is not None` (web app startup sets the flag)
- Env var `FEATURE_LIBRARY` to override (e.g. force-disable for managed instances)
- `/api/config/features` response extended with `library_enabled: bool`

## Non-Goals

- Automatic background sync Dropbox ↔ R2 after cutover
- Non-admin "contributor" uploads (admin-only in v1)
- Virus/malware scanning of uploads (MIME/size allowlist only)
- CDN or edge caching layer
- Changing Instagram/Telegram/email publisher contracts
- Orchestrator UI changes (orchestrator owns its own upload UI)
- Thumbnails in migration (managed storage regenerates via Pillow on demand — PUB-024)

## Acceptance Criteria

### Migration CLI

- **AC1**: Migration tool runs as `uv run python -m publisher_v2.tools.migrate_storage --source-folder <path> --target-prefix <prefix>` and requires `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `MIGRATE_DROPBOX_REFRESH_TOKEN`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_ENDPOINT_URL`, `R2_BUCKET_NAME` env vars. Missing required vars → clear error message and exit code 1.
- **AC2**: `--dry-run` lists files with sizes that would be copied, outputs summary `{total_files, total_bytes}`, writes nothing to R2.
- **AC3**: Normal run copies each image from Dropbox to R2 target prefix preserving filename. For each image, if a `.txt` sidecar exists in Dropbox, it is also copied.
- **AC4**: Subfolder structure is preserved: images in `archive/`, `keep/`, `remove/` under the Dropbox source folder are copied to matching subprefixes under the R2 target prefix.
- **AC5**: Idempotency: re-running the tool skips files where the target key already exists. When Dropbox `content_hash` is available and target `ETag` differs, the file is re-copied (overwritten).
- **AC6**: `--limit N` copies at most N images (excludes sidecars from the count).
- **AC7**: Per-file errors (download/upload failure) are logged and counted; the tool continues and prints a summary with `{copied, skipped, errors}` at exit. Exit code 0 if no errors, 1 if any errors.
- **AC8**: No secrets (`refresh_token`, `access_key_id`, `secret_access_key`) appear in log output. `SanitizingFilter` covers migration log keys.

### Admin Library API

- **AC9**: `GET /api/library/objects` returns paginated object list when `config.managed` is set. Returns 404 when `config.managed is None` or `library_enabled` is false.
- **AC10**: `POST /api/library/upload` accepts multipart `image/jpeg` and `image/png` files up to 20 MB; returns 415 for disallowed MIME types and 413 for oversized files. Uploaded file appears in managed storage at the instance's `image_folder` prefix.
- **AC11**: `POST /api/library/upload` rate-limits to 10 uploads/minute per admin session; returns 429 on exceed.
- **AC12**: `DELETE /api/library/objects/{filename}` deletes the image and its `.txt` sidecar (if present) from managed storage. Returns 404 if the image does not exist.
- **AC13**: `POST /api/library/objects/{filename}/move` moves the image + sidecar to the target logical folder. Returns 400 for invalid target folder values.
- **AC14**: All library endpoints require `require_auth` + `require_admin`; unauthenticated requests receive 401, non-admin requests receive 403.

### Admin Library UI

- **AC15**: Library panel is visible in the admin UI only when the user is admin AND `library_enabled` is true in `/api/config/features`. Hidden for Dropbox-only instances.
- **AC16**: Upload flow: file picker validates MIME + size client-side before sending; upload progress is shown; success/error feedback displayed.
- **AC17**: Delete flow: confirmation dialog before calling DELETE endpoint; object removed from list on success.
- **AC18**: Move flow: dropdown with target folder options; object list refreshes after successful move.

### Feature flag

- **AC19**: `FeaturesConfig.library_enabled` defaults to `False`. When `config.managed is not None`, the web app sets it to `True` at startup unless overridden by `FEATURE_LIBRARY=false`.
- **AC20**: `/api/config/features` includes `library_enabled` in its response.

### Security and quality

- **AC21**: No credential material (`access_key_id`, `secret_access_key`, `refresh_token`) appears in any API response or log output.
- **AC22**: Preview mode is not affected by library routes (library is a web-only feature; migration CLI is not part of preview).
- **AC23**: Zero new `ruff check` or `mypy` violations in touched files.
- **AC24**: Tests cover: migration dry-run, migration copy+skip, migration per-file error handling, library CRUD endpoints (auth + success + error cases), feature flag behavior, upload validation (MIME, size, rate limit).

### Documentation

- **AC25**: `docs_v2/03_Architecture/ARCHITECTURE.md` updated with library endpoints and migration CLI reference.
- **AC26**: Cutover checklist documented in handoff: ordered steps for Dropbox→managed migration including orchestrator `storage_provider` flip, rollback, and "do not publish until cutover complete" guidance.

## Implementation Notes

### Migration CLI design
- Module: `publisher_v2/tools/migrate_storage.py` (new `tools/` package under `publisher_v2/`)
- Constructs `DropboxStorage` and `ManagedStorage` directly (bypasses `ApplicationConfig` and `create_storage`)
- Uses `argparse` for CLI args, `asyncio.run()` for entry
- Progress via `log_json(logger, INFO, "migration_progress", copied=N, skipped=N, errors=N, total=N)` every 10 files
- Hash comparison: Dropbox `content_hash` (from `list_images_with_hashes`) vs R2 `ETag` (from `head_object`). These are different hash algorithms so exact match is unreliable — for `--resume`, existence check is the primary gate; hash comparison is best-effort (log warning on mismatch, re-copy)

### Admin library design
- Router: `publisher_v2/src/publisher_v2/web/routers/library.py`
- Depends on `get_request_service` for storage + config access
- `list_objects`: uses `boto3` paginator via `asyncio.to_thread` (not `list_images` — needs size/metadata, not just filenames)
- `upload`: `UploadFile.read()` → `storage.client.put_object(Bucket=..., Key=..., Body=..., ContentType=...)` via `asyncio.to_thread`
- Filename sanitization: `pathlib.PurePosixPath(filename).name` to strip directory traversal, `unicodedata.normalize("NFC", ...)` for unicode
- Rate limit: in-memory dict keyed by admin cookie value, sliding window counter; no external dependency

### Sidecar metadata note
- `DropboxStorage.get_file_metadata` returns `{"id": ..., "rev": ...}`; `ManagedStorage.get_file_metadata` returns `{"ETag": ..., "LastModified": ...}`
- `build_metadata_phase1` takes `dropbox_file_id` and `dropbox_rev` — for managed storage these are `None` (fields omitted from sidecar). This is correct behavior: migrated sidecars retain their original Dropbox metadata; new sidecars on managed storage simply lack Dropbox-specific fields.
- **No migration of sidecar content is needed** — sidecars are copied byte-for-byte from Dropbox.

### Cutover checklist (for handoff)
1. Run migration with `--dry-run` — verify file count matches expectation
2. Run migration (full copy) — verify `{copied, skipped, errors}` summary
3. Verify objects in R2 via orchestrator admin or `aws s3 ls`
4. In orchestrator: update instance `storage_provider` from `"dropbox"` to `"managed"` and set credential ref
5. Verify publisher serves images from managed storage (visit admin UI, check thumbnails)
6. **Do not publish until cutover is verified** — publishing during transition may archive to wrong backend
7. Rollback: revert orchestrator `storage_provider` to `"dropbox"`; Dropbox content is untouched (migration is copy, not move)

### Dependencies
- `boto3` and `Pillow` already added in PUB-024

## Related

- [PUB-023: Storage Protocol Extraction](archive/PUB-023_storage-protocol-extraction.md) (Done)
- [PUB-024: Managed Storage Adapter](archive/PUB-024_managed-storage-adapter.md) (Done)
- [PUB-022: Orchestrator Schema V2 Integration](archive/PUB-022_orchestrator-schema-v2.md) (Done)
- Platform Orchestrator: runtime projection + credential resolution (contract owner)

---

*2026-03-16 — Spec hardened for Claude Code handoff*
