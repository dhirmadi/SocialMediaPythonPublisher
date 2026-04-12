# PUB-031: Managed Storage Migration & Admin Library

| Field | Value |
|-------|-------|
| **ID** | PUB-031 |
| **Category** | Storage / Web UI |
| **Priority** | P1 |
| **Effort** | L |
| **Status** | Not Started |
| **Dependencies** | PUB-023, PUB-024 |

## Problem

Orchestrator staging/production can expose instances with **`storage.provider: "managed"`** (S3-compatible / R2) and **`/v1/credentials/resolve`** payloads with **`provider: "managed"`**. Publisher V2 today is Dropbox-only in orchestrator wiring and always constructs `DropboxStorage`. Operators need a **safe path from Dropbox to managed** without breaking existing Dropbox-bound hosts, and tenant **admins need a way to curate the image library** (not only keep/remove/archive in the posting workflow) when content lives in object storage.

## Desired Outcome

1. **Compatibility**: Any instance whose runtime config still has **`storage.provider: "dropbox"`** behaves exactly as today (no regressions for existing domains).
2. **Migration**: A supported, repeatable way to **copy objects** from the tenant’s Dropbox layout to the managed key prefix (images + sidecars), with **idempotency**, **progress reporting**, and **dry-run**; clear **cutover** steps coordinated with orchestrator (`storage_provider` / credential ref changes).
3. **Admin library**: **Authenticated admin** users (existing HTTP auth + admin cookie + Auth0 where enabled) can **list, upload, delete, and optionally move** objects under the instance’s managed prefix via the Publisher web app, within documented limits (size, MIME allowlist, rate limits).

## Scope

### Phase A — Preconditions (no duplicate work)

- Assumes **PUB-023** (`StorageProtocol`) and **PUB-024** (`ManagedStorage` + factory + orchestrator parsing for `managed` / credential resolution) are implemented or updated so `OrchestratorConfigSource` and `WebImageService` inject the correct adapter.
- **Amendment to PUB-024 non-goals**: arbitrary **admin bulk upload** and **migration** are delivered **here** (PUB-031), not in PUB-024, so PUB-024 can stay focused on protocol parity and workflow-identical behavior.

### Phase B — Dropbox → managed migration

- **Operator tooling** (preferred first delivery): documented CLI or maintenance command (e.g. `uv run python -m publisher_v2.tools.migrate_storage …`) that:
  - Reads **source** Dropbox credentials + paths (from env/INI or from orchestrator for a given host, per product choice).
  - Reads **target** managed credentials + prefix from orchestrator resolution (same shape as runtime).
  - Copies **images and sidecars** (e.g. `.txt`, other configured sidecar extensions) preserving relative paths under `archive` / `keep` / `remove` as appropriate.
  - Supports **`--dry-run`**, **`--limit`**, resume/idempotency (skip if destination key exists and size/ETag matches), and structured logging (no secrets).
  - Respects **Dropbox API** and **S3** rate limits; uses `asyncio.to_thread` for blocking SDKs.
- **Cutover checklist** in this item’s handoff: orchestrator steps (e.g. verify object listing in R2, then flip `storage_provider`), rollback notes, and **“do not publish until cutover complete”** guidance.

### Phase C — Admin library (Publisher web)

- New **admin-only** API routes + minimal UI (consistent with existing single-page admin patterns):
  - List objects under tenant prefix (paginated).
  - Upload (multipart or presigned flow — pick one in hardening; default preference: **server-side upload via Publisher** with strict body size limits so secrets never reach the browser).
  - Delete object (+ sidecar siblings where applicable).
  - Optional: move between logical folders (`root` / `archive` / `keep` / `remove`) matching orchestrator path semantics.
- **Authorization**: reuse existing admin gates; no weakening of auth.
- **Feature flag** or config gate: library UI enabled only for **`managed`** (and optionally hidden for Dropbox-only instances).

### Cross-repo / product boundaries

- **Orchestrator**: instance `storage_provider`, credential ref rows, and any **first-party upload UI on org.shibari.photo** remain orchestrator-owned; this item references them only as **dependencies** and cutover steps. If “single place to upload” is later decided to be orchestrator-only, Publisher admin upload scope can be reduced to delete/list/move only — document that decision at harden time.

## Non-Goals

- Changing Instagram/Telegram/email publisher contracts.
- Non-admin “contributor” uploads (only admin library in v1).
- Automatic background sync Dropbox ↔ R2 after cutover (out of scope unless explicitly added later).
- Virus/malware scanning of uploads (optional future); v1 may rely on MIME/size allowlist only.

## Acceptance Criteria

### Compatibility

- **AC1**: Integration tests (or contract tests) prove **`provider: "dropbox"`** runtime still builds `DropboxConfig` + `DropboxStorage` and existing Dropbox-dominated flows pass unchanged.
- **AC2**: **`provider: "managed"`** runtime builds managed adapter; no code path forces Dropbox for managed tenants.

### Migration

- **AC3**: Migration tool supports **`--dry-run`** listing counts/bytes that would be copied without writing.
- **AC4**: Successful copy is **idempotent** (re-run does not duplicate or corrupt; skips or verifies matches).
- **AC5**: Sidecars adjacent to images are copied with the same relative naming rules the workflow expects.
- **AC6**: Documentation lists **ordered cutover steps** and **rollback** (revert `storage_provider` + operational caveats).

### Admin library

- **AC7**: Non-admin users cannot call library endpoints (401/403 consistent with existing web security).
- **AC8**: Upload rejects disallowed types and oversize files with clear errors; no credential material in responses or logs.
- **AC9**: Delete removes image + known sidecar pattern(s) or documents orphan behavior explicitly in AC.

### Quality

- **AC10**: Tests cover migration idempotency and admin authz; `ruff` + `mypy` clean for touched modules.
- **AC11**: `docs_v2/03_Architecture/ARCHITECTURE.md` updated for new endpoints and behavior.

## Implementation Notes

- **Key layout**: align migration targets with orchestrator-projected paths (`{tenant_slug}/{instance_name}/…` under managed storage); do not invent a second layout.
- **Credential provider**: orchestrator returns **`provider: "managed"`** for managed storage resolution — Publisher credential models must match (not a generic `"s3"` string unless orchestrator changes).
- **Preview / dry-publish**: migration tooling must not confuse “preview mode” with migration; migration is an explicit operator action, not part of `WorkflowOrchestrator` preview.
- Consider **etag/content_hash** mapping for dedup after migration vs Dropbox `content_hash` (document any behavioral difference for vision/dedup).

## Related

- [PUB-023: Storage Protocol Extraction](PUB-023_storage-protocol-extraction.md)
- [PUB-024: Managed Storage Adapter](PUB-024_managed-storage-adapter.md)
- [PUB-022: Orchestrator Schema V2 Integration](archive/PUB-022_orchestrator-schema-v2.md)
- Platform Orchestrator: runtime projection + `ManagedStorageCredentialsResponse` (contract owner for credential JSON)

## “Did we miss anything?” — Checklist for hardening

Capture decisions for:

| Topic | Why it matters |
|-------|----------------|
| **Dedup / workflow state** | After migration, Publisher-local caches or state files keyed by Dropbox paths may need invalidation or keying by storage adapter. |
| **Vision / temp URLs** | OpenAI vision needs fetchable URLs; presigned expiry must exceed analysis window; Dropbox links vs R2 presign semantics differ. |
| **Thumbnails** | PUB-024 may cache/regenerate thumbnails; migration does not need to copy Dropbox-rendered thumbs if server-side regen is acceptable — state explicitly. |
| **Partial failure** | Migration stopped mid-way: resume rules and operator visibility (per-prefix checkpoints). |
| **Multi-dyno** | Admin upload + workflow concurrent writes: eventual consistency and listing staleness. |
| **Orchestrator-only uploads** | If product prefers uploads only on orchestrator UI, Phase C shrinks to list/delete/move + deep link. |
