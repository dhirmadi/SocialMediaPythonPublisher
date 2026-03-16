# PUB-010: Keep/Remove Curation Controls

| Field | Value |
|-------|-------|
| **ID** | PUB-010 |
| **Category** | Web UI |
| **Priority** | INF |
| **Effort** | M |
| **Status** | Done |
| **Dependencies** | PUB-005 |

## Problem

Today, when reviewing candidate images in the V2 web interface, the only admin actions are **Analyze & caption** and **Publish**. There is no quick way to curate images that should be **kept for later** (e.g., approved for a future posting batch) or **removed from the current candidate pool** without publishing or manually moving files in Dropbox. This makes it hard to maintain a clean "to post" folder, explicitly mark images as "keep for later" vs. "remove from current selection", and ensure removed images are not re-selected by the main workflow.

## Desired Outcome

Two admin-only **Keep** and **Remove** curation actions in the web UI. **Keep** moves the current image and its sidecars into a configurable `folder_keep` subfolder. **Remove** moves the image and sidecars into a configurable `folder_remove` subfolder (with backward-compatible support for existing `folder_reject`). Both actions use existing Dropbox/storage abstractions, move all relevant sidecars, are gated by feature flags and config, respect preview/dry-run safety, and are exposed as admin-only buttons next to Analyze and Publish.

## Scope

- **Keep** button: server-side move of image + sidecars to `[Dropbox].folder_keep`
- **Remove** button: server-side move of image + sidecars to `[Dropbox].folder_remove` (or legacy `folder_reject`)
- New endpoints: `POST /api/images/{filename}/keep`, `POST /api/images/{filename}/remove`
- Config: `folder_keep`, `folder_remove` in INI `[Dropbox]`; `.env` overrides
- Reuse of archive/sidecar movement patterns; no destructive delete
- Admin-only; protected by HTTP auth + admin cookie; hidden when feature disabled

## Acceptance Criteria

- AC1: Given authenticated admin and `folder_keep` configured, when I click **Keep**, the image and sidecars are moved to `folder_keep`; UI shows confirmation and advances to next image
- AC2: Given authenticated admin and `folder_remove` (or `folder_reject`) configured, when I click **Remove**, the image and sidecars are moved; UI indicates moved (not deleted) and advances to next image
- AC3: Given preview/dry-run mode, Keep/Remove perform no Dropbox moves; system logs/previews what would have happened
- AC4: Given not authenticated or not admin, Keep/Remove buttons are hidden and endpoints return 401/403
- AC5: Given feature disabled or not configured, no Keep/Remove buttons or endpoints
- AC6: Given `folder_reject` exists and no `folder_remove`, config loader populates `folder_remove` from `folder_reject`

## Implementation Notes

- Extend `DropboxStorage` with reusable "move image + sidecars" helper; reused by archive, Keep, and Remove
- Orchestrator-level curation entry points accept filename and action (Keep/Remove); delegate to preview utilities in preview/dry mode
- Separate `keep_enabled` and `remove_enabled` feature flags for flexibility
- Moving out of `image_folder` is sufficient; no additional deduplication state updates

## Related

- [Original feature doc](../../08_Epics/002_web_admin_curation_ux/010_keep_remove_curation/010_feature.md) — full historical detail
