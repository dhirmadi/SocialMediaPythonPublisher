<!-- docs_v2/08_Epics/08_02_Feature_Design/010_keep-remove-curation_design.md -->

# Keep/Remove Curation Controls — Feature Design

**Feature ID:** 010  
**Feature Name:** keep-remove-curation  
**Design Version:** 1.0  
**Date:** 2025-11-21  
**Status:** Design Review  
**Author:** Architecture Team  

---

## 1. Summary

### Problem
The V2 web interface currently allows an authenticated admin to:
- View a random image from the configured Dropbox image folder.
- Run AI analysis and caption/sd_caption generation.
- Publish the image via existing publishers, which archives it on success.

However, there is no first-class curation mechanism to:
- Mark images as “keep for later” without publishing them.
- Remove images from the main candidate pool without deleting them or manually moving files in Dropbox.

Operators must either publish, leave images in place, or manually organize folders in Dropbox, which is slow and error-prone.

### Goals
1. Add two admin-only **Keep** and **Remove** actions to the web UI for the currently displayed image.
2. Implement corresponding server-side curation operations that:
   - Move the image (and sidecars) from the main image folder into configurable `folder_keep` and `folder_remove` subfolders.
   - Reuse or mirror existing archive/sidecar movement patterns.
3. Make Keep/Remove behavior controlled via configuration and feature flags, with:
   - New `[Dropbox]` INI keys `folder_keep` and `folder_remove` (with aliasing from `folder_reject`).
   - `.env` overrides `folder_keep` and `folder_remove`.
   - Feature toggles keeping Keep and Remove independently switchable.
4. Preserve preview/dry-run safety guarantees (no Dropbox moves in preview/dry; human-readable preview instead).
5. Keep admin security tight: curation actions are admin-only, hidden from non-admin users, and protected by existing HTTP auth + admin cookie.

### Non-Goals
- Batch/queue-based curation or bulk actions across multiple images.
- New storage providers or changes to Dropbox as the single source of truth.
- Changes to sidecar file formats or caption/analysis schemas.
- CLI-facing curation commands (web-only in this feature).
- Any destructive delete operation — this feature is move-only.

---

## 2. Context & Assumptions

### Current State
- **Configuration & schema**
  - `DropboxConfig` currently exposes:
    - `image_folder` — the root folder to pull candidate images from.
    - `archive_folder` — subfolder under `image_folder` for archived (published) images.
  - The sample `configfiles/fetlife.ini` already includes legacy keys:
    - `folder_keep = approve`
    - `folder_reject = reject`
  - `load_application_config()` in `config/loader.py` reads:
    - Dropbox credentials from `.env`.
    - Dropbox folder names and content flags from INI.
    - Feature toggles `FEATURE_ANALYZE_CAPTION` and `FEATURE_PUBLISH` from `.env` into `FeaturesConfig`.

- **Storage / Dropbox**
  - `DropboxStorage` implements:
    - `list_images`, `list_images_with_hashes`, `download_image`, `get_temporary_link`, `get_file_metadata`.
    - `archive_image(folder, filename, archive_folder)`:
      - Creates `archive_folder` as a subdirectory under `folder` (if needed).
      - Moves the image via `files_move_v2`.
      - Attempts to move the `.txt` sidecar alongside the image, ignoring “not found”.
  - Sidecars:
    - Stable-diffusion caption sidecar `.txt` is written next to the image (`write_sidecar_text`).
    - Additional sidecar metadata flows are described in docs and supported by sidecar parser logic.

- **Workflow**
  - `WorkflowOrchestrator.execute()` performs:
    1. Image selection from `DropboxStorage` with deduplication.
    2. Temporary local file creation and Dropbox temporary link.
    3. AI vision analysis (feature-gated via `config.features.analyze_caption_enabled`).
    4. Caption + sd_caption generation and sidecar write (also feature-gated).
    5. Publish via enabled `Publisher`s (feature-gated via `config.features.publish_enabled`).
    6. Archive to `archive_folder` on success (plus dedup state updates).
  - Preview mode (`--preview`) calls into `WorkflowOrchestrator.execute(..., preview_mode=True)` and uses `publisher_v2.utils.preview` utilities to print human-readable output, with explicit guarantees of no side effects.

- **Web app**
  - `publisher_v2.web.app` provides:
    - `GET /` → HTML UI (`index.html`).
    - `GET /api/images/random` → `WebImageService.get_random_image()`.
    - `POST /api/images/{filename}/analyze` → `WebImageService.analyze_and_caption()`.
    - `POST /api/images/{filename}/publish` → `WebImageService.publish_image()`.
  - All mutating endpoints require:
    - `require_auth` (HTTP bearer/basic).
    - `require_admin` (admin cookie), when admin mode is configured.
  - `WebImageService`:
    - Loads config via `load_application_config`.
    - Binds `DropboxStorage`, `AIService`, `WorkflowOrchestrator`, and publishers.
    - Implements sidecar-aware analysis/captioning and publishing, including web-specific sidecar writes.

- **Web UI**
  - `index.html` renders:
    - Image display and basic caption panel.
    - Admin-only controls:
      - “Analyze & caption” and “Publish” buttons.
    - Admin login/logout and admin status panel.
  - JS uses:
    - `/api/admin/login`, `/api/admin/status`, `/api/admin/logout`.
    - `/api/config/features` to control Analyze/Publish button visibility based on `FeaturesConfig`.

### Assumptions
1. `folder_keep` and `folder_remove` are *relative* subfolder names under `DropboxConfig.image_folder`, consistent with `archive_folder`.
2. Legacy `folder_reject` INI key should be treated as a backward-compatible alias for `folder_remove` when `folder_remove` is not explicitly set.
3. `.env` variables `folder_keep` and `folder_remove` (lower-case for compatibility with existing V1-style config) override INI values for the same logical fields.
4. Keep/Remove feature toggles are implemented as part of `FeaturesConfig` and configured via environment variables, similar to existing feature toggles.
5. Keep/Remove applied via the web interface are always “live” operations (non-preview), while CLI workflows may use new curation helpers in preview/dry contexts for non-destructive behavior.

---

## 3. Requirements

### Functional Requirements

**FR1: Dropbox configuration**
- Extend `DropboxConfig` with:
  - `folder_keep: Optional[str]` — name of the “keep” subfolder (relative to `image_folder`).
  - `folder_remove: Optional[str]` — name of the “remove” subfolder (relative to `image_folder`).
- Update `load_application_config()` to:
  - Read `[Dropbox].folder_keep` and `[Dropbox].folder_remove` (if present).
  - Treat `[Dropbox].folder_reject` as a legacy alias for `folder_remove` when `folder_remove` is not set.
  - Override these with `.env` variables:
    - `folder_keep`
    - `folder_remove`
  - Ensure resulting values are safe path components (no absolute paths, `..`, or path separators).

**FR2: Feature toggles**
- Extend `FeaturesConfig` and configuration loader to support:
  - `keep_enabled: bool` (default `True`) from `FEATURE_KEEP_CURATE` env var.
  - `remove_enabled: bool` (default `True`) from `FEATURE_REMOVE_CURATE` env var.
- Update `/api/config/features` to expose Keep/Remove enablement to the web UI.
- When `keep_enabled` or `remove_enabled` is `False`, corresponding UI controls must be hidden and server endpoints must reject curation with a 403-style error.

**FR3: Storage-level move helpers**
- Extend `DropboxStorage` with a generic move helper:
  - `async def move_image_with_sidecars(self, folder: str, filename: str, target_subfolder: str) -> None`
  - Behavior:
    - Ensure `target_subfolder` is created under `folder` (`files_create_folder_v2`).
    - Move the main image from `{folder}/{filename}` to `{folder}/{target_subfolder}/{filename}` via `files_move_v2`.
    - Attempt to move the `.txt` sidecar (`{stem}.txt`) from `{folder}/{stem}.txt` to `{folder}/{target_subfolder}/{stem}.txt`, ignoring “not found”.
    - May be used by both archive and curation behaviors.
- Update `archive_image()` to delegate to `move_image_with_sidecars` for the core move logic (minimizing duplication while preserving semantics).

**FR4: Orchestrator curation API**
- Add new methods to `WorkflowOrchestrator`:
  - `async def keep_image(self, filename: str, *, preview_mode: bool = False, dry_run: bool = False) -> None`
  - `async def remove_image(self, filename: str, *, preview_mode: bool = False, dry_run: bool = False) -> None`
- Behavior:
  - Resolve destination subfolder from `self.config.dropbox.folder_keep` / `folder_remove` (with `folder_reject` alias via config).
  - If the corresponding feature flag (`features.keep_enabled` / `features.remove_enabled`) is `False`, log and raise a domain-level error (e.g., `StorageError` or a dedicated curation error).
  - If destination is not configured (empty or `None`), raise a clear `StorageError`/`ConfigurationError`.
  - In **preview or dry-run modes**:
    - Do **not** call `DropboxStorage.move_image_with_sidecars`.
    - Use `preview` utilities (or a small helper) to print/log what would happen, including filename and target folder.
  - In normal mode:
    - Call `move_image_with_sidecars` with `image_folder` and the appropriate subfolder.
    - Log structured events (`workflow_keep_image`, `workflow_remove_image`) with correlation id, filename, and destination.

**FR5: Web service integration**
- Extend `WebImageService` with:
  - `async def keep_image(self, filename: str) -> Dict[str, Any]`
  - `async def remove_image(self, filename: str) -> Dict[str, Any]`
- Behavior:
  - Validate that `features.keep_enabled` / `features.remove_enabled` are `True`; otherwise raise `PermissionError`.
  - Ensure the file exists by attempting `get_temporary_link` or simply relying on storage move exceptions; translate “not found” into `FileNotFoundError` for the API layer.
  - Delegate to `WorkflowOrchestrator.keep_image()` / `remove_image()` with `preview_mode=False`, `dry_run=False`.
  - Return a small dict describing:
    - `filename`
    - `action` (`"keep"` or `"remove"`)
    - `destination_folder`
    - `preview_only: bool` (always `False` in web path).

**FR6: Web API endpoints**
- Add new FastAPI endpoints in `web.app`:
  - `POST /api/images/{filename}/keep`
  - `POST /api/images/{filename}/remove`
- Both endpoints must:
  - Call `require_auth(request)`.
  - If `is_admin_configured()`, call `require_admin(request)`.
  - Use `RequestTelemetry` for correlation and timing metrics.
  - Delegate to `WebImageService.keep_image()` / `remove_image()`.
  - Map:
    - `FileNotFoundError` → HTTP 404.
    - `PermissionError` (feature disabled) → HTTP 403.
    - Any other error → HTTP 500.
  - Return a small response model (`CurationResponse`) with the fields described in FR5.

**FR7: Web UI changes**
- Update `index.html` to:
  - Add two new admin-only buttons:
    - “Keep” (`btn-keep`)
    - “Remove” (`btn-remove`)
  - Place them next to existing “Analyze & caption” and “Publish” buttons in the admin controls group.
- Update JS to:
  - Extend `featureConfig` to include `keep_enabled` and `remove_enabled`.
  - Use `/api/config/features` to gate visibility and enabled state of Keep/Remove buttons.
  - Add `apiKeep()` and `apiRemove()` functions that:
    - Require `currentFilename` and `isAdmin` like Analyze/Publish.
    - POST to `/api/images/{filename}/keep` or `/remove`.
    - Handle 401/403 by clearing admin state and prompting re-login.
    - On success:
      - Show a clear status message (“Moved to keep/remove: …”).
      - Trigger a “Next image” load to advance to the next candidate.
    - On error:
      - Surface a concise error message in the status panel.

**FR8: Preview/dry behavior**
- CLI / workflow integration:
  - New curation methods in `WorkflowOrchestrator` must support preview/dry flags and:
    - Avoid Dropbox moves.
    - Use preview utilities to print “Would move {image} → {folder_keep/folder_remove}”.
  - No changes to existing `execute()` preview semantics (archive and publish flows remain unchanged).
- Web:
  - For this feature, web paths always operate in non-preview mode (no CLI flags); they perform real moves when invoked.

### Non-Functional Requirements
- **Performance**
  - Curation operations should be comparable in latency to archive:
    - One or two `files_move_v2` operations plus optional folder creation.
  - Avoid introducing additional Dropbox list operations on the hot path.
- **Security**
  - Keep/Remove endpoints are admin-only and require both HTTP auth and admin cookie.
  - No secrets appear in responses or logs; only filenames and folders are logged.
- **Backwards compatibility**
  - If `folder_keep`/`folder_remove` are not configured and/or features are disabled, behavior is identical to current state (no extra UI controls, no new behavior).
  - Existing configs using `folder_reject` continue working via aliasing.

---

## 4. Architecture & Design

### 4.1 Configuration & Schema

**Updates to `DropboxConfig`**
- Add optional fields:
```python
class DropboxConfig(BaseModel):
    app_key: str = Field(..., description="Dropbox application key")
    app_secret: str = Field(..., description="Dropbox application secret")
    refresh_token: str = Field(..., description="OAuth2 refresh token")
    image_folder: str = Field(..., description="Source image folder path in Dropbox")
    archive_folder: str = Field(default="archive", description="Archive folder name (relative)")
    folder_keep: Optional[str] = Field(
        default=None,
        description="Subfolder name under image_folder for Keep curation moves",
    )
    folder_remove: Optional[str] = Field(
        default=None,
        description="Subfolder name under image_folder for Remove curation moves (alias for legacy folder_reject)",
    )
```

**Updates to `FeaturesConfig`**
```python
class FeaturesConfig(BaseModel):
    analyze_caption_enabled: bool = Field(
        default=True,
        description="Enable AI vision analysis and caption generation feature",
    )
    publish_enabled: bool = Field(
        default=True,
        description="Enable publishing feature (all platforms)",
    )
    keep_enabled: bool = Field(
        default=True,
        description="Enable Keep curation action in web/CLI flows",
    )
    remove_enabled: bool = Field(
        default=True,
        description="Enable Remove curation action in web/CLI flows",
    )
```

**Updates to `load_application_config`**
- Read INI keys:
  - `folder_keep = cp.get("Dropbox", "folder_keep", fallback=None)`
  - `folder_remove = cp.get("Dropbox", "folder_remove", fallback=None)`
  - Legacy alias:
    - If `folder_remove` is `None` and `cp.has_option("Dropbox", "folder_reject")`, then:
      - `folder_remove = cp.get("Dropbox", "folder_reject")`
- Apply `.env` overrides:
  - `env_keep = os.environ.get("folder_keep") or None`
  - `env_remove = os.environ.get("folder_remove") or None`
  - If set, override the INI-derived values.
- Validate subfolder names:
  - Reject values containing `/`, `\`, or `..` (to avoid path traversal and maintain “subfolder under image_folder” semantics).
- Extend `FeaturesConfig` population:
```python
features_cfg = FeaturesConfig(
    analyze_caption_enabled=parse_bool_env(
        os.environ.get("FEATURE_ANALYZE_CAPTION"), True, var_name="FEATURE_ANALYZE_CAPTION"
    ),
    publish_enabled=parse_bool_env(
        os.environ.get("FEATURE_PUBLISH"), True, var_name="FEATURE_PUBLISH"
    ),
    keep_enabled=parse_bool_env(
        os.environ.get("FEATURE_KEEP_CURATE"), True, var_name="FEATURE_KEEP_CURATE"
    ),
    remove_enabled=parse_bool_env(
        os.environ.get("FEATURE_REMOVE_CURATE"), True, var_name="FEATURE_REMOVE_CURATE"
    ),
)
```

### 4.2 Storage Layer

**New helper in `DropboxStorage`**

```python
class DropboxStorage:
    # ...

    async def move_image_with_sidecars(
        self,
        folder: str,
        filename: str,
        target_subfolder: str,
    ) -> None:
        """
        Move the image and known sidecar(s) from folder/filename to
        folder/target_subfolder/filename using server-side moves.
        """
        # Implementation wraps dropbox.files_move_v2 and files_create_folder_v2
```

Key details:
- `target_subfolder` is treated as a simple folder name; we compute:
  - `dst_dir = os.path.join(folder, target_subfolder)`
  - `dst = os.path.join(dst_dir, filename)`
- Reuse sidecar movement logic from `archive_image`:
  - `.txt` sidecar at `os.path.join(folder, f"{stem}.txt")` → `os.path.join(dst_dir, f"{stem}.txt")`.
- Wrap operations in `asyncio.to_thread` and use existing tenacity retry decorator (similar to `archive_image`).

**Refactor `archive_image`**
- Replace the inline move logic with a call to `move_image_with_sidecars(folder, filename, archive_folder)`.
- Preserve retry behavior and `StorageError` wrapping.

### 4.3 Workflow Orchestrator

**New curation methods**

```python
class WorkflowOrchestrator:
    # ...

    async def keep_image(
        self,
        filename: str,
        *,
        preview_mode: bool = False,
        dry_run: bool = False,
    ) -> None:
        # Resolve folder_keep
        # Enforce feature flag
        # Delegate to storage or preview utilities

    async def remove_image(
        self,
        filename: str,
        *,
        preview_mode: bool = False,
        dry_run: bool = False,
    ) -> None:
        # Same pattern for folder_remove
```

Proposed behavior:
- Common helper `_curate_image(filename, target_subfolder, action_name, preview_mode, dry_run)` that:
  - Validates `target_subfolder` is non-empty.
  - In preview/dry:
    - Logs a `workflow_curation_preview` event.
    - Optionally calls a new `preview.print_curation_action(...)` helper for CLI output.
  - In normal mode:
    - Calls `self.storage.move_image_with_sidecars(self.config.dropbox.image_folder, filename, target_subfolder)`.
    - Logs `workflow_keep_image` or `workflow_remove_image` with correlation id and folder.
- Feature gating:
  - `keep_image` requires `self.config.features.keep_enabled is True`.
  - `remove_image` requires `self.config.features.remove_enabled is True`.
- Error handling:
  - Storage-level `StorageError` and Dropbox `ApiError` remain the primary sources for I/O failures; orchestrator logs and re-raises them.

### 4.4 Web Service Layer

**`WebImageService` extensions**

Add methods:

```python
class WebImageService:
    # ...

    async def keep_image(self, filename: str) -> Dict[str, Any]:
        if not self.config.features.keep_enabled:
            raise PermissionError("Keep feature is disabled via FEATURE_KEEP_CURATE toggle")
        # Optionally verify existence via get_temporary_link
        await self.orchestrator.keep_image(filename, preview_mode=False, dry_run=False)
        dest = self.config.dropbox.folder_keep
        return {
            "filename": filename,
            "action": "keep",
            "destination_folder": dest,
            "preview_only": False,
        }

    async def remove_image(self, filename: str) -> Dict[str, Any]:
        if not self.config.features.remove_enabled:
            raise PermissionError("Remove feature is disabled via FEATURE_REMOVE_CURATE toggle")
        await self.orchestrator.remove_image(filename, preview_mode=False, dry_run=False)
        dest = self.config.dropbox.folder_remove
        return {
            "filename": filename,
            "action": "remove",
            "destination_folder": dest,
            "preview_only": False,
        }
```

**Web response model**

Add `CurationResponse` to `web.models`:

```python
class CurationResponse(BaseModel):
    filename: str
    action: str  # "keep" or "remove"
    destination_folder: str
    preview_only: bool = False
```

### 4.5 Web API & Auth

**New endpoints in `web.app`**

```python
@app.post(
    "/api/images/{filename}/keep",
    response_model=CurationResponse,
    responses={404: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 403: {"model": ErrorResponse}},
)
async def api_keep_image(...):
    await require_auth(request)
    if is_admin_configured():
        require_admin(request)
    # Delegate to WebImageService.keep_image and log timing
```

Same pattern for `/remove`.

**Feature config endpoint**

Extend `/api/config/features` to include Keep/Remove flags:

```python
return {
    "analyze_caption_enabled": features.analyze_caption_enabled,
    "publish_enabled": features.publish_enabled,
    "keep_enabled": features.keep_enabled,
    "remove_enabled": features.remove_enabled,
}
```

Auth:
- Reuse existing `require_auth` and `require_admin` patterns.
- Non-admin users:
  - Do not see Keep/Remove buttons in UI.
  - Cannot trigger endpoints (401/403 returned).

### 4.6 Web UI & UX

**HTML changes (`index.html`)**
- Add two buttons inside `#admin-controls`:
  - `<button id="btn-keep" class="secondary">Keep</button>`
  - `<button id="btn-remove" class="secondary">Remove</button>`
- Mark them as admin-only (same visibility rules as other admin controls).

**JS changes**
- Extend `featureConfig`:

```js
let featureConfig = {
  analyze_caption_enabled: true,
  publish_enabled: true,
  keep_enabled: true,
  remove_enabled: true,
};
```

- Update `fetchFeatureConfig` and `updateAdminUI` to:
  - Show/hide Keep/Remove buttons based on `keep_enabled` / `remove_enabled`.
  - Disable them when not in admin mode.
- Add `apiKeep` and `apiRemove` functions:
  - `POST` to `/api/images/{filename}/keep` and `/remove`.
  - Handle 401/403 by clearing admin state and prompting re-login (same as Analyze/Publish).
  - On success, show a message like `"Moved to keep: <filename> → <folder>"` and then call `apiGetRandom()` to fetch the next image.

Responsiveness:
- Keep existing mobile-first layout; additional buttons are in the same responsive button group and will wrap naturally on small screens.

### 4.7 Preview Utilities

**New helper in `utils.preview`**

Add a small helper to surface curation preview in CLI:

```python
def print_curation_action(filename: str, source_folder: str, target_subfolder: str, action: str) -> None:
    print("\n📂 CURATION ACTION (PREVIEW)")
    print("─" * 70)
    print(f"  Action:   {action}")
    print(f"  File:     {filename}")
    print(f"  From:     {source_folder}")
    print(f"  To:       {source_folder.rstrip('/')}/{target_subfolder}")
```

This is invoked by `WorkflowOrchestrator.keep_image/remove_image` when `preview_mode`/`dry_run` are `True`.

---

## 5. Data Model Changes

### Configuration Models
- `DropboxConfig`:
  - **New:** `folder_keep: Optional[str]`
  - **New:** `folder_remove: Optional[str]` (alias for legacy `folder_reject` INI key).
- `FeaturesConfig`:
  - **New:** `keep_enabled: bool = True`
  - **New:** `remove_enabled: bool = True`

### Web Models
- `CurationResponse` (new) in `web.models`.

### No Persistent Data Schema Changes
- No changes to sidecar formats or metadata schemas.
- No new databases or persistent stores introduced.

---

## 6. API Changes

### Web API

- **New endpoints**
  - `POST /api/images/{filename}/keep`
    - Request: none (path-only).
    - Response: `CurationResponse`.
    - Auth: HTTP auth + admin cookie required.
  - `POST /api/images/{filename}/remove`
    - Same shape and auth as `keep`.

- **Updated endpoints**
  - `GET /api/config/features`
    - Now includes `keep_enabled` and `remove_enabled` flags.

### CLI
- No changes to CLI flags or entrypoint behavior.
- New orchestrator curation methods are available for future CLI integrations or tests.

---

## 7. Error Handling

### Configuration Errors
- Invalid `folder_keep` or `folder_remove` values (containing `/`, `\`, or `..`) result in `ConfigurationError` during startup.
- Missing required Dropbox/OpenAI env vars continue to raise existing configuration errors.

### Runtime Errors
- Dropbox move failures:
  - Wrapped as `StorageError` from `DropboxStorage`.
  - Logged with structured events (`keep_image_error`, `remove_image_error`).
  - Surface as HTTP 500 in web endpoints.
- Feature disabled:
  - In web service, `PermissionError` is raised when Keep/Remove toggles are disabled; surfaced as HTTP 403 with a clear message.
- File not found:
  - If storage reports a missing file, `FileNotFoundError` is surfaced as HTTP 404 in web endpoints.

---

## 8. Testing Strategy

### Unit Tests
- **Configuration & loader**
  - INI-only configuration:
    - `folder_keep`/`folder_remove` values correctly loaded into `DropboxConfig`.
    - `folder_reject` populates `folder_remove` when `folder_remove` is absent.
  - `.env` overrides:
    - `folder_keep` and `folder_remove` override INI values.
  - Path validation:
    - Values with `/`, `\`, or `..` raise `ConfigurationError`.
  - Feature flags:
    - `FEATURE_KEEP_CURATE` and `FEATURE_REMOVE_CURATE` parsed via `parse_bool_env` for various truthy/falsey inputs.

### Integration Tests
- **Storage**
  - `move_image_with_sidecars`:
    - Moves image and `.txt` sidecar to a target subfolder.
    - Does not fail if sidecar is absent.
  - `archive_image` still archives correctly using the refactored helper.

- **Workflow orchestration**
  - `keep_image`:
    - With feature enabled and valid `folder_keep`, calls storage helper once with expected arguments.
    - In preview/dry mode, does not call storage; uses preview helper and logs.
  - `remove_image`:
    - Same pattern as keep, including preview behavior.
  - Missing configuration:
    - If `folder_keep`/`folder_remove` are not configured, raise errors and do not call storage.

- **Web service + API**
  - `WebImageService.keep_image/remove_image`:
    - When features enabled and folders configured, delegations succeed and return correct destination data.
    - When features disabled, raise `PermissionError`.
  - FastAPI endpoints:
    - Auth + admin checks enforced (401/403 on missing/invalid credentials).
    - 404 returned when image does not exist.
    - 403 returned when features disabled.

- **Web UI**
  - Existing web UI tests extended to:
    - Verify Keep/Remove buttons only appear for admin sessions.
    - Verify button visibility respects feature flags from `/api/config/features`.
    - Verify successful Keep/Remove triggers a status message and subsequent “Next image” load.

### Preview & Safety
- Tests under preview mode:
  - Verify that Keep/Remove preview helpers print “Would move …” and do not call storage.
  - Verify preview footer still accurately states that no images are moved or archived.

---

## 9. Migration & Rollout

### Migration Path
1. Deploy code changes with feature toggles defaulting to `True`.
2. Existing deployments with `folder_reject` configured:
   - `folder_remove` will be derived from `folder_reject`.
   - No behavior change until web curation endpoints are used.
3. Operators can opt into full Keep/Remove behavior by:
   - Setting `[Dropbox].folder_keep` / `[Dropbox].folder_remove` in INI, and/or
   - Setting `.env` `folder_keep` / `folder_remove` values.

### Rollout Plan
1. Enable feature in development/staging:
   - Configure keep/remove folders and verify end-to-end curation flows from the web UI.
2. Validate:
   - No regressions in archive, Analyze, or Publish flows.
   - Keep/Remove work as expected and respect feature toggles.
3. Roll out to production with feature toggles and curation folders configured.

### Rollback Plan
- If issues arise:
  - Disable Keep/Remove via `FEATURE_KEEP_CURATE=false` and/or `FEATURE_REMOVE_CURATE=false` (web UI controls disappear).
  - Optionally revert code changes to restore previous behavior.
  - Existing archive flows continue to work due to shared helper.

---

## 10. Documentation Updates

- **Configuration docs**
  - Update `docs_v2/05_Configuration/CONFIGURATION.md`:
    - New `[Dropbox]` keys: `folder_keep`, `folder_remove` (and legacy `folder_reject` alias).
    - New `.env` variables: `folder_keep`, `folder_remove`.
    - New feature toggles: `FEATURE_KEEP_CURATE`, `FEATURE_REMOVE_CURATE`.
  - Clarify that keep/remove folders are subfolders under `image_folder`.

- **Feature docs**
  - Final shipped doc under `docs_v2/08_Epics/010_keep-remove-curation.md`:
    - How to configure and use the Keep/Remove buttons.
    - Safety semantics and preview/dry behavior.

---

## 11. Success Criteria

### Functional
- ✅ Admin users see **Keep** and **Remove** buttons in the web UI when feature toggles and folders are configured.
- ✅ Clicking **Keep** moves the current image and its sidecars into the configured `folder_keep` subfolder and loads the next image.
- ✅ Clicking **Remove** moves the current image and its sidecars into the configured `folder_remove` subfolder and loads the next image.
- ✅ Existing archive behavior remains unchanged for published images.
- ✅ Preview/dry workflows never perform real Dropbox moves but log/print intended curation actions.

### Non-Functional
- ✅ No regressions in performance or stability of archive, Analyze, or Publish flows.
- ✅ No secrets are logged or exposed via new endpoints.
- ✅ Behavior is fully backward compatible when keep/remove are disabled or unconfigured.

---

## 12. References

- Feature Request: `docs_v2/08_Epics/08_01_Feature_Request/010_keep-remove-curation.md`  
- Configuration Loader: `publisher_v2/src/publisher_v2/config/loader.py`  
- Configuration Schema: `publisher_v2/src/publisher_v2/config/schema.py`  
- Storage: `publisher_v2/src/publisher_v2/services/storage.py`  
- Workflow Orchestrator: `publisher_v2/src/publisher_v2/core/workflow.py`  
- Web App & Service: `publisher_v2/src/publisher_v2/web/app.py`, `publisher_v2/src/publisher_v2/web/service.py`  
- Web Models & Auth: `publisher_v2/src/publisher_v2/web/models.py`, `publisher_v2/src/publisher_v2/web/auth.py`  
- Preview Utilities: `publisher_v2/src/publisher_v2/utils/preview.py`  


