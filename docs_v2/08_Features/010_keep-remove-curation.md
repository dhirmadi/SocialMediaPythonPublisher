<!-- docs_v2/08_Features/010_keep-remove-curation.md -->

# Feature 010 — Keep/Remove Curation Controls (Shipped)

**Status:** Shipped  
**Feature ID:** 010  
**Related Docs:**  
- Request: `docs_v2/08_Features/08_01_Feature_Request/010_keep-remove-curation.md`  
- Design: `docs_v2/08_Features/08_02_Feature_Design/010_keep-remove-curation_design.md`  
- Plan: `docs_v2/08_Features/08_03_Feature_plan/010_keep-remove-curation_plan.yaml`  

---

## Summary

This feature adds two new **admin-only curation actions** to the V2 web UI and workflow:

- **Keep** → move the current image (and its sidecars/metadata) into a configurable `folder_keep` subfolder under the main Dropbox image folder.
- **Remove** → move the current image (and its sidecars/metadata) into a configurable `folder_remove` subfolder under the main Dropbox image folder, with backward-compatible support for legacy `folder_reject`.

Both actions:

- Use Dropbox **server-side moves** through the existing `DropboxStorage` abstraction.
- Move the primary image and any Stable-Diffusion/metadata sidecars together.
- Are controlled via **feature toggles** and config/`.env` settings.
- Are only exposed to authenticated **admin** users (same HTTP auth + admin cookie as Analyze/Publish).

Preview/dry CLI workflows can now preview Keep/Remove operations without mutating Dropbox state.

---

## Goals & Non-Goals

**Goals**

- Provide a fast, safe way for admins in the web UI to:
  - Mark images as **“keep for later”** (Keep).
  - Move images out of the main candidate pool without deleting them (Remove).
- Reuse the existing Dropbox sidecar movement patterns from archive for curation moves.
- Make curation behavior configurable via `[Dropbox]` INI and `.env`, and guarded by feature flags.
- Preserve preview/dry safety guarantees (no real moves in preview/dry).
- Keep admin protections consistent with existing web admin flows.

**Non-Goals**

- Batch or multi-image curation workflows.
- Hard delete semantics for images or sidecars.
- Any change to sidecar file formats or core AI analysis/caption behavior.
- New CLI flags or commands for Keep/Remove (web-only in this feature).

---

## User Value & UX

### Web UI Behavior

When an admin is logged in and Keep/Remove are enabled/configured:

- The **admin controls** area now shows four buttons:
  - **Analyze & caption**
  - **Publish**
  - **Keep**
  - **Remove**
- Keep and Remove:
  - Are **hidden** for non-admin users and when disabled by feature flags.
  - Are disabled when the admin session expires or when an image is not loaded.

Actions:

- **Keep**
  - Moves the current image and its sidecars from `[Dropbox].image_folder` into `[Dropbox].image_folder/[Dropbox].folder_keep`.
  - Shows a status like:  
    `Moved to keep: image.jpg → keep.`
  - Automatically loads the next random image.

- **Remove**
  - Moves the current image and its sidecars from `[Dropbox].image_folder` into `[Dropbox].image_folder/[Dropbox].folder_remove` (or `folder_reject` via alias).
  - Shows a status like:  
    `Moved to remove folder (not deleted): image.jpg → remove`
  - Automatically loads the next random image.

Error handling:

- If a Keep/Remove feature is disabled or not configured, the corresponding buttons are hidden; direct API calls return HTTP 403 with a clear message.
- Dropbox/other errors are surfaced as short status messages in the UI and structured logs on the server; no secrets are logged.

---

## Technical Overview

### Configuration: INI & Environment

**New `[Dropbox]` keys**

In your INI (e.g., `configfiles/fetlife.ini`):

```ini
[Dropbox]
image_folder = /Photos/bondage_fetlife
archive = archive
folder_keep = approve          ; Keep/approve folder (relative to image_folder)
folder_remove = reject         ; Remove/reject folder (relative to image_folder)
; legacy configs may still use:
; folder_reject = reject
```

Rules:

- `folder_keep` and `folder_remove` are **relative subfolder names** under `image_folder`.
- They must be simple names **without** `/`, `\`, or `..`. Invalid values raise a `ConfigurationError` at startup.
- Legacy `folder_reject` is treated as a **backward-compatible alias** for `folder_remove` when `folder_remove` is not explicitly set.

**New `.env` overrides**

Environment variables override INI values:

- `folder_keep=<keep-subfolder-name>` → overrides `[Dropbox].folder_keep`
- `folder_remove=<remove-subfolder-name>` → overrides `[Dropbox].folder_remove` (after `folder_reject` alias)

These allow per-environment curation folder names (e.g., staging vs. production) without editing the INI.

**New feature toggles**

The existing feature toggle section now includes:

```text
FEATURE_KEEP_CURATE=true|false   (default: true)
FEATURE_REMOVE_CURATE=true|false (default: true)
```

Semantics:

- When `FEATURE_KEEP_CURATE=false`:
  - `config.features.keep_enabled` is `False`.
  - Keep buttons are hidden and web `/keep` returns HTTP 403.
- When `FEATURE_REMOVE_CURATE=false`:
  - `config.features.remove_enabled` is `False`.
  - Remove buttons are hidden and web `/remove` returns HTTP 403.

The `/api/config/features` endpoint now returns:

```json
{
  "analyze_caption_enabled": true,
  "publish_enabled": true,
  "keep_enabled": true,
  "remove_enabled": true
}
```

The web UI uses these flags to hide/show admin controls.

### Schema & Loader

**Updated `DropboxConfig`**

- Added:
  - `folder_keep: Optional[str]`
  - `folder_remove: Optional[str]`

**Updated `FeaturesConfig`**

- Added:
  - `keep_enabled: bool = True`
  - `remove_enabled: bool = True`

**Loader behavior (`load_application_config`)**

- Reads:
  - `[Dropbox].image_folder` and `archive`.
  - Optional `[Dropbox].folder_keep` and `[Dropbox].folder_remove`.
  - Legacy `[Dropbox].folder_reject` → used when `folder_remove` is not set.
- Applies `.env` overrides:
  - `folder_keep`, `folder_remove`.
- Validates:
  - Rejects keep/remove values containing `/`, `\`, or `..` with a `ConfigurationError`.
- Populates `FeaturesConfig` from:
  - `FEATURE_ANALYZE_CAPTION`, `FEATURE_PUBLISH`, `FEATURE_KEEP_CURATE`, `FEATURE_REMOVE_CURATE` (all via the shared `parse_bool_env` helper).

---

## Core Workflow & Storage Changes

### Storage: `DropboxStorage`

**New helper**

- `move_image_with_sidecars(folder, filename, target_subfolder)`:
  - Creates `folder/target_subfolder` if needed.
  - Moves the image from `folder/filename` → `folder/target_subfolder/filename`.
  - Attempts to move the sidecar `folder/<stem>.txt` → `folder/target_subfolder/<stem>.txt`, ignoring “not found” errors.
  - Uses tenacity retries and wraps Dropbox `ApiError` in `StorageError`.

**Archive refactor**

- `archive_image(folder, filename, archive_folder)` now delegates to `move_image_with_sidecars`, keeping archive semantics and retries but centralizing Dropbox move logic.

### Orchestrator: `WorkflowOrchestrator`

**New methods**

- `keep_image(filename, *, preview_mode=False, dry_run=False)`
- `remove_image(filename, *, preview_mode=False, dry_run=False)`

Both delegate to a shared private helper:

- `_curate_image(filename, target_subfolder, action, preview_mode, dry_run)`:
  - Validates that the target subfolder (keep/remove) is configured.
  - When `preview_mode` or `dry_run` is `True`:
    - Calls `preview.print_curation_action(...)`.
    - Logs a `workflow_curation_preview` event.
    - Does **not** call Dropbox.
  - When live:
    - Calls `storage.move_image_with_sidecars(image_folder, filename, target_subfolder)`.
    - Logs `workflow_curation_start` and `workflow_curation_complete`.

Feature gating:

- `keep_image`:
  - Requires `config.features.keep_enabled is True`.
  - Otherwise raises `StorageError("Keep feature is disabled via FEATURE_KEEP_CURATE toggle")`.
- `remove_image`:
  - Requires `config.features.remove_enabled is True`.
  - Otherwise raises `StorageError("Remove feature is disabled via FEATURE_REMOVE_CURATE toggle")`.

### Preview utilities

**New helper in `utils.preview`**

- `print_curation_action(filename, source_folder, target_subfolder, action)`:
  - Prints a simple, human-readable preview block:
    - Action (keep/remove)
    - File
    - From (source folder)
    - To (computed subfolder path)

Preview footer remains accurate: no images are moved/archived in preview; Keep/Remove preview paths respect that rule.

---

## Web API & UI Details

### Web Service (`WebImageService`)

**New methods**

- `keep_image(filename) -> CurationResponse`
  - Ensures `config.features.keep_enabled` is `True`; otherwise raises `PermissionError`.
  - Delegates to `orchestrator.keep_image(filename, preview_mode=False, dry_run=False)`.
  - Returns `CurationResponse` with:
    - `filename`
    - `action = "keep"`
    - `destination_folder = config.dropbox.folder_keep or ""`

- `remove_image(filename) -> CurationResponse`
  - Ensures `config.features.remove_enabled` is `True`; otherwise raises `PermissionError`.
  - Delegates to `orchestrator.remove_image(...)`.
  - Returns `CurationResponse` with:
    - `filename`
    - `action = "remove"`
    - `destination_folder = config.dropbox.folder_remove or ""`

### Web Models

**New model**

- `CurationResponse`:

```python
class CurationResponse(BaseModel):
    filename: str
    action: str  # "keep" or "remove"
    destination_folder: str
    preview_only: bool = False
```

### FastAPI Endpoints

**New endpoints**

- `POST /api/images/{filename}/keep`
- `POST /api/images/{filename}/remove`

Both:

- Require HTTP auth (`require_auth`) and admin cookie (`require_admin` when configured).
- Delegate to `WebImageService.keep_image/remove_image`.
- Map:
  - `FileNotFoundError` → HTTP 404.
  - `PermissionError` → HTTP 403.
  - Any other error → HTTP 500 with generic detail.
- Log completion/error with correlation IDs and timing.

**Updated endpoint**

- `GET /api/config/features` now includes:

```json
{
  "analyze_caption_enabled": true,
  "publish_enabled": true,
  "keep_enabled": true,
  "remove_enabled": true
}
```

### HTML/JS Template (`index.html`)

**Admin controls**

- The admin button row (`#admin-controls`) now includes:

```html
<button id="btn-analyze" class="secondary">Analyze &amp; caption</button>
<button id="btn-publish" class="secondary">Publish</button>
<button id="btn-keep" class="secondary">Keep</button>
<button id="btn-remove" class="secondary">Remove</button>
```

**JS state (`featureConfig`)**

- Extended to:

```js
let featureConfig = {
  analyze_caption_enabled: true,
  publish_enabled: true,
  keep_enabled: true,
  remove_enabled: true,
};
```

**Visibility & enablement**

- `updateAdminUI()` now hides/shows and disables/enables Keep/Remove based on:
  - `isAdmin`
  - `featureConfig.keep_enabled` / `featureConfig.remove_enabled`

**New API calls**

- `apiKeep()`:
  - POSTs to `/api/images/{filename}/keep`.
  - Handles 401/403 by clearing admin state and prompting re-login.
  - On success:
    - Shows a keep status message.
    - Calls `apiGetRandom()` to load the next image.

- `apiRemove()`:
  - POSTs to `/api/images/{filename}/remove`.
  - Same auth handling as Keep.
  - On success:
    - Shows a “moved, not deleted” status message.
    - Loads the next image.

Both handlers are wired into `initLayout()` and respect existing admin-mode behavior.

---

## Testing & Quality

The following tests were added or extended:

- **Config & env**
  - `test_config_keep_remove.py`
    - INI + `.env` loading for `folder_keep`/`folder_remove`.
    - Legacy `folder_reject` alias for `folder_remove`.
    - Invalid folder names raise `ConfigurationError`.
    - `FEATURE_KEEP_CURATE` and `FEATURE_REMOVE_CURATE` default/override behavior.

- **Storage**
  - `test_dropbox_keep_remove_move.py`
    - `move_image_with_sidecars` moves image + `.txt` sidecar to target subfolder.
    - Missing sidecar is ignored.
    - `archive_image` delegates to `move_image_with_sidecars`.

- **Workflow**
  - `test_workflow_keep_remove.py`
    - `keep_image` and `remove_image` call storage with configured folders.
    - Preview mode uses `print_curation_action` and does not call storage.
    - Disabled keep/remove flags raise `StorageError`.

- **Web service**
  - `web/test_web_keep_remove_service.py`
    - `WebImageService.keep_image/remove_image` delegate to orchestrator and respect feature flags.

- **Web endpoints**
  - `web_integration/test_web_keep_remove_endpoints.py`
    - Keep/Remove endpoints require admin cookie.
    - Authenticated flows succeed (or 404 depending on actual Dropbox state); no auth bypass.

- **Feature config endpoint**
  - `web/test_publishers_endpoint.py` updated to expect and assert `keep_enabled`/`remove_enabled` in `/api/config/features`.

All existing tests continue to pass (`127 passed`), and no behavioral regressions were observed.

---

## Rollout Notes & Backward Compatibility

- Default behavior is **backward-compatible**:
  - If `folder_keep`/`folder_remove` are not configured or Keep/Remove flags are disabled:
    - No new buttons appear in the UI.
    - No new API paths are used.
    - CLI and web behaviors remain unchanged.
- Existing configs using `folder_reject` continue to work:
  - `folder_remove` is derived from `folder_reject` when not set.
- Preview/dry CLI runs:
  - Continue to show “no images moved or archived” guarantees.
  - Keep/Remove code paths use preview output only, with no Dropbox moves.

To enable the feature:

1. Add keep/remove folders in INI (example):

```ini
[Dropbox]
image_folder = /Photos/bondage_fetlife
archive = archive
folder_keep = approve
folder_remove = reject
```

2. Optionally add `.env` overrides:

```env
FEATURE_KEEP_CURATE=true
FEATURE_REMOVE_CURATE=true
folder_keep=approve
folder_remove=reject
```

3. Ensure web admin auth is configured (`web_admin_pw` + `WEB_AUTH_*`) and reload the app.

Admins will then see Keep/Remove buttons in the web UI and can curate images safely from their browser.

---

## Artifacts

- **Feature Request:** `docs_v2/08_Features/08_01_Feature_Request/010_keep-remove-curation.md`
- **Design:** `docs_v2/08_Features/08_02_Feature_Design/010_keep-remove-curation_design.md`
- **Plan:** `docs_v2/08_Features/08_03_Feature_plan/010_keep-remove-curation_plan.yaml`
- **Implementation (selected):**
  - `config/schema.py` — `DropboxConfig.folder_keep/folder_remove`, `FeaturesConfig.keep_enabled/remove_enabled`
  - `config/loader.py` — INI/env wiring, validation, feature toggles
  - `services/storage.py` — `move_image_with_sidecars`, refactored `archive_image`
  - `core/workflow.py` — `keep_image`, `remove_image`, curation preview
  - `utils/preview.py` — `print_curation_action`
  - `web/models.py` — `CurationResponse`
  - `web/service.py` — `keep_image`, `remove_image`
  - `web/app.py` — `/keep` and `/remove` endpoints, extended `/api/config/features`
  - `web/templates/index.html` — Keep/Remove UI and JS wiring
- **Documentation:** `docs_v2/05_Configuration/CONFIGURATION.md` updated with new Dropbox keys, env vars, and feature toggles.


