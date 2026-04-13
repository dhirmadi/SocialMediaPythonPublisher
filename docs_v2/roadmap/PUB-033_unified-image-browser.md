# PUB-033: Unified Image Browser

| Field | Value |
|-------|-------|
| **ID** | PUB-033 |
| **Category** | Web UI |
| **Priority** | P1 |
| **Effort** | M |
| **Status** | Proposal |
| **Dependencies** | PUB-031 (Done), PUB-032 (Done) |

## Problem

The admin UI has two disconnected ways to interact with images:

1. **Main view**: A single random/sequential image viewer with analyze/publish/keep/remove actions. The "Browse" button opens a modal with a thumbnail grid from `GET /api/images/list`, but this only shows the inbox folder, has no upload/delete, no search, and uses a completely different data path.
2. **Library panel**: A separate admin-only table panel with full CRUD (list, upload, delete, move), search, sort, and folder filtering via `GET /api/library/objects`. Only available for managed storage instances.

This means admins constantly switch context between "browsing images" and "managing images". The library table is functional but un-visual for a photography product — operators want to see thumbnails, not filenames. The browse grid is visual but has no management capabilities.

## Desired Outcome

One unified "Browse" experience: click Browse, see a **thumbnail grid** of all images. From there:
- **Click** a thumbnail to select it → opens the detail/analyze/publish workflow for that image
- **Upload** new images directly into the grid
- **Delete** images from the grid
- **Search** and **sort** the grid (reusing PUB-032's sort/filter/offset API)
- The old separate library panel is **removed**

The publisher UI no longer exposes archive/keep/remove folder tabs — those are storage internals irrelevant to the publisher admin's daily workflow. The unified browser shows only the inbox (root) folder.

## Scope

### Part A: Unified browse grid (replaces browse modal + library panel)

Replace the existing `showBrowseModal()` thumbnail grid and the `#panel-library` panel with a single, permanent browse view:

- **Thumbnail grid**: Visual grid of images using `/api/images/{filename}/thumbnail?size=w256h256`
- **Data source**: `GET /api/library/objects` (with sort/filter/offset from PUB-032) — provides filenames + size + date for display. Scoped to root folder only (no `prefix` parameter).
- **Image selection**: Click a thumbnail → fetches `GET /api/images/{filename}` → populates the main image viewer with detail/caption/analyze/publish controls (same `applyImageData` flow)
- **Pagination**: Previous/Next page buttons with offset arithmetic (from PUB-032)
- **Search**: Text input (300ms debounce), filters by filename substring (reuses `q` parameter)
- **Sort**: Dropdown (Name / Date / Size) + order toggle (reuses `sort` + `order` parameters)
- **Result count**: "Showing X–Y of Z" display

### Part B: Upload from the browser

- **Upload button** at the top of the grid (same position as current library toolbar)
- File picker: `accept="image/jpeg,image/png"`, multi-file support
- Calls `POST /api/library/upload` (existing endpoint, unchanged)
- Upload progress bar (reuse existing library upload progress UX)
- On success: refresh the grid to show the new image
- Rate limit (existing 10/min) — UI shows clear error on 429

### Part C: Delete from the browser

- **Delete button** per thumbnail (small `×` icon overlay, visible on hover/touch)
- Confirmation dialog before calling `DELETE /api/library/objects/{filename}`
- On success: remove the thumbnail from the grid
- Gated behind `delete_enabled` feature flag (existing)

### Part D: Remove old library panel

- Remove the `#panel-library` HTML section from `index.html`
- Remove all `library*` JS functions (fetch, upload, delete, move, init, pagination) that were specific to the library panel
- Remove the `libraryFetchObjects`, `libraryUpload`, `libraryDelete`, `libraryMove`, `initLibrary`, `updateLibraryVisibility` functions
- The library **API router** (`/api/library/*`) is **kept** — it backs the unified browser. Only the old UI panel is removed.
- `library_enabled` feature flag still controls whether the unified browse grid has upload/delete capabilities (browse-to-view works regardless for managed storage; upload/delete are admin+library_enabled)

### Part E: Navigation changes

- **"Browse" button** opens the unified grid view (not a modal — a panel that replaces the main image area, or a full-screen overlay)
- **Clicking a thumbnail** in the grid returns to the single-image detail view with that image loaded
- **"Back to grid"** button returns from detail view to the grid (preserving scroll position / page / search state)
- **"Next" button** in detail view advances to the next image in the current grid order (not random)
- **Swipe gestures**: Swipe left/right in detail view navigates to next/previous image in grid order
- **The random "publish mode"** is removed — all image navigation is now explicit (grid → select → next/prev)

### Part F: Feature flag / availability

- The unified browser works for **both** Dropbox and managed storage instances
- For Dropbox instances: the grid uses `GET /api/images/list` + thumbnails (no upload/delete, no sort/filter — those require library API which is managed-only)
- For managed storage instances: full capabilities (sort, filter, upload, delete via library API)
- `library_enabled` controls whether upload/delete controls appear in the grid
- `delete_enabled` controls whether the per-image delete button appears

## Non-Goals

- Folder tabs for archive/keep/remove (not needed in the publisher workflow)
- Drag-and-drop upload (file picker is sufficient for v1)
- Bulk select / bulk delete (single-image actions only for v1)
- Image preview lightbox with zoom (click goes to detail view, not a lightbox)
- Changes to the analyze/publish/keep/remove actions (those remain in the detail view)

## Acceptance Criteria

- AC1: "Browse" opens a thumbnail grid showing images from the instance's root folder
- AC2: Clicking a thumbnail loads that image in the detail view with full analyze/publish/keep/remove controls
- AC3: A "Back to grid" control returns to the browse grid preserving current search/sort/page state
- AC4: Upload button in the grid triggers file upload via `POST /api/library/upload` (managed storage only)
- AC5: Per-thumbnail delete button (when `delete_enabled`) calls `DELETE /api/library/objects/{filename}` with confirmation
- AC6: Search input filters the grid by filename substring (managed storage only, uses `q` parameter)
- AC7: Sort dropdown and order toggle control grid order (managed storage only, uses `sort`/`order` parameters)
- AC8: The old `#panel-library` section and its JS are removed from `index.html`
- AC9: The library API router (`/api/library/*`) is unchanged — all existing endpoints still work
- AC10: For Dropbox instances, the grid shows thumbnails from `GET /api/images/list` without upload/delete/sort/filter
- AC11: "Next" and "Previous" in detail view navigate sequentially through the current grid order (not random)
- AC12: The random "publish mode" (`apiGetRandom`) is removed; all image selection is explicit
- AC13: Mobile-responsive grid (2 columns on small screens, 3-4 on larger)
- AC14: `ruff` / `mypy` / `pytest` gates pass

## Implementation Notes

- The grid is not a separate page — it's a panel/view state within `index.html` (same single-page architecture)
- View state: `"grid"` vs `"detail"` — toggled by clicking a thumbnail or "Back to grid"
- Grid state persists across grid↔detail transitions: `gridOffset`, `gridSort`, `gridOrder`, `gridQ`, `gridImages[]`, `gridCurrentIndex`
- Detail view "Next"/"Previous" use `gridImages[gridCurrentIndex ± 1]` — no random, no separate review list
- For Dropbox: `GET /api/images/list` returns filenames; thumbnails via `GET /api/images/{filename}/thumbnail`; no size/date metadata (sort by name only, no search)
- For managed: `GET /api/library/objects` returns filenames + metadata; thumbnails via same `/api/images/{filename}/thumbnail`; full sort/filter/pagination

## Related

- [PUB-031: Managed Storage Migration & Admin Library](archive/PUB-031_managed-storage-migration-admin-library.md) — original library API and UI
- [PUB-032: Admin Library — Sorting & Filtering](archive/PUB-032_library-list-sort-filter.md) — sort/filter/offset API this reuses
- [PUB-019: Swipe Gestures & Workflow Modes](archive/PUB-019_swipe-workflow-modes.md) — swipe navigation this supersedes
