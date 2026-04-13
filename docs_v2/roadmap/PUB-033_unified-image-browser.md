# PUB-033: Unified Image Browser

| Field | Value |
|-------|-------|
| **ID** | PUB-033 |
| **Category** | Web UI |
| **Priority** | P1 |
| **Effort** | L |
| **Status** | Hardened |
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

---

## Part A — Grid view panel (replaces browse modal + library panel)

Replace `showBrowseModal()` (dynamic DOM creation) and the `#panel-library` HTML with a **static grid panel** inside `<main>`:

```html
<div id="panel-grid" class="hidden">
  <!-- toolbar: search, sort, order, upload, count -->
  <!-- grid container: .browse-grid already exists in CSS -->
  <!-- pagination bar -->
</div>
```

**Data source** — branched by storage provider:
- **Managed storage**: `GET /api/library/objects?limit=24&offset=0&sort=name&order=asc` — returns `{ objects: [{key, size, last_modified}], total_in_window, truncated }`. The `key` field is the filename.
- **Dropbox**: `GET /api/images/list` — returns `{ images: [filename, ...] }`. No metadata (size/date), no server-side sort/filter.

Thumbnails in both paths use the existing `GET /api/images/{filename}/thumbnail?size=w256h256`.

**Grid layout** — reuse the existing `.browse-grid` CSS (`grid-template-columns: repeat(auto-fill, minmax(140px, 1fr))`). This naturally yields ~2 columns on mobile, 3-4 on desktop. Each cell is a `.browse-grid-item` with `<img>`, a filename label, and (for managed+admin) a delete overlay icon.

**Page size** — `GRID_PAGE_SIZE = 24` items per page. Managed uses `limit=24&offset=N`. Dropbox slices the in-memory filename array.

### Acceptance Criteria

- **AC-A1**: `#panel-grid` is a static `<div>` inside `<main>`, toggled via `classList.add/remove("hidden")`. Not a dynamic modal.
- **AC-A2**: Managed instances call `GET /api/library/objects?limit=24&offset={gridOffset}&sort={gridSort}&order={gridOrder}&q={gridQ}` to populate the grid.
- **AC-A3**: Dropbox instances call `GET /api/images/list` once, cache the result (`browseImageList` / 60 s TTL), and paginate client-side.
- **AC-A4**: Each grid cell shows a lazy-loaded thumbnail (`loading="lazy"`, `src="/api/images/{encodeURIComponent(fname)}/thumbnail?size=w256h256"`), filename label, and (if managed + admin + `delete_enabled`) a `×` delete overlay.
- **AC-A5**: Mobile-responsive: `.browse-grid` uses `grid-template-columns: repeat(auto-fill, minmax(140px, 1fr))` (existing CSS, no change needed).
- **AC-A6**: "Showing X–Y of Z" result count below toolbar. For managed: X = `offset+1`, Y = `offset + objects.length`, Z = `total_in_window`. For Dropbox: Z = `browseImageList.length`.
- **AC-A7**: Pagination bar with Previous / page numbers / Next. Previous disabled when `offset === 0`. Next disabled when `offset + GRID_PAGE_SIZE >= total`. Page numbers use `getPaginationRange()` (existing helper).

---

## Part B — View state machine (grid ↔ detail)

The UI has two view states managed by a `viewState` variable:

| State | Visible | Hidden |
|-------|---------|--------|
| `"detail"` | `.image-container`, `.controls`, `#panel-caption`, `#panel-admin`, `#panel-activity` | `#panel-grid` |
| `"grid"` | `#panel-grid` | `.image-container`, `.controls`, `#panel-caption` |

Admin/activity panels remain hidden during grid view because the grid is the active workspace.

**State transitions**:
- **"Browse" button click** → `setViewState("grid")`, fetch + render grid
- **Thumbnail click** → record `gridCurrentIndex`, call `GET /api/images/{filename}` → `applyImageData(data)` → `setViewState("detail")`
- **"Back to grid" button** → `setViewState("grid")` — grid re-renders at the same `gridOffset`, `gridSort`, `gridOrder`, `gridQ` (no re-fetch needed if data is cached; re-fetch if stale)
- **"Next" / "Previous" in detail view** → `gridCurrentIndex ± 1`; if within current page's `gridImages[]`, call `GET /api/images/{filename}` → `applyImageData`. If past page boundary, fetch next/previous page first.
- **Keep / Remove / Delete in detail view** → after the action completes, remove the image from `gridImages[]`, adjust `gridCurrentIndex`, auto-advance to the next image (or back to grid if none remain on this page).

**`setViewState(state)` function**:
```javascript
function setViewState(state) {
  viewState = state;
  const gridPanel = document.getElementById("panel-grid");
  const imageContainer = document.querySelector(".image-container");
  const controls = document.querySelector(".controls");
  const captionPanel = document.getElementById("panel-caption");
  if (state === "grid") {
    gridPanel.classList.remove("hidden");
    imageContainer.classList.add("hidden");
    controls.classList.add("hidden");
    captionPanel.classList.add("hidden");
  } else {
    gridPanel.classList.add("hidden");
    imageContainer.classList.remove("hidden");
    controls.classList.remove("hidden");
    captionPanel.classList.remove("hidden");
  }
}
```

### Acceptance Criteria

- **AC-B1**: Global `viewState` variable (`"grid"` | `"detail"`), default `"detail"`.
- **AC-B2**: `setViewState("grid")` hides `.image-container`, `.controls`, `#panel-caption`; shows `#panel-grid`.
- **AC-B3**: `setViewState("detail")` shows `.image-container`, `.controls`, `#panel-caption`; hides `#panel-grid`.
- **AC-B4**: Clicking a thumbnail calls `GET /api/images/{filename}` → `applyImageData(data)` → `setViewState("detail")`. The grid's `gridOffset`, `gridSort`, `gridOrder`, `gridQ` are preserved (not reset).
- **AC-B5**: "Back to grid" button (inside `.controls` or `.image-container`) calls `setViewState("grid")` without re-fetching if the grid data is already loaded.
- **AC-B6**: "Next" in detail view increments `gridCurrentIndex` within `gridImages[]`; fetches `GET /api/images/{gridImages[gridCurrentIndex]}` → `applyImageData`. If index reaches end of current page, fetches next page first.
- **AC-B7**: "Previous" in detail view decrements `gridCurrentIndex`; same fetch pattern. If index goes below 0, fetches previous page first (if `gridOffset > 0`).
- **AC-B8**: After keep/remove/delete action in detail view, the affected image is spliced from `gridImages[]`, `gridCurrentIndex` is adjusted, and the next image loads automatically. If `gridImages` is empty, returns to grid with a re-fetch.

---

## Part C — Search, sort, upload, delete in the grid toolbar

### Search (managed storage only)
- Text `<input>` in the toolbar with `placeholder="Search..."`.
- Debounce 300 ms. On input, sets `gridQ = value`, `gridOffset = 0`, re-fetches.
- For Dropbox instances: search input is **hidden** (no server-side filter available).

### Sort + Order (managed storage only)
- `<select>` with options: Name, Date, Size → maps to `sort=name|last_modified|size`.
- Order toggle button (`↑`/`↓`) → `order=asc|desc`.
- On change: `gridOffset = 0`, re-fetch.
- For Dropbox instances: sort and order controls are **hidden**.

### Upload (managed storage + admin + `library_enabled`)
- Upload `<label>` + hidden `<input type="file" accept="image/jpeg,image/png" multiple>`.
- On change: iterate files, call `POST /api/library/upload` (existing) per file sequentially.
- Progress bar below toolbar (reuse existing `#library-upload-progress` pattern).
- On success: refresh the grid (`gridOffset = 0`, re-fetch).
- On 429: show toast "Upload rate limit reached. Try again shortly."
- For Dropbox instances or non-admin: upload controls are **hidden**.

### Delete (managed storage + admin + `delete_enabled`)
- Small `×` button overlaid on each thumbnail (visible on hover/touch via CSS `:hover` / `pointer: coarse` media query).
- On click (stop propagation to prevent thumbnail selection): `confirm("Delete {filename}?")` → `DELETE /api/library/objects/{filename}`.
- On success: remove the `<div>` from the grid, decrement result count.
- For Dropbox instances or non-admin or `!delete_enabled`: delete overlay is **not rendered**.

### Acceptance Criteria

- **AC-C1**: Search input visible only for managed storage. Typing triggers re-fetch after 300 ms debounce with `q={value}&offset=0`.
- **AC-C2**: Sort dropdown and order toggle visible only for managed storage. Changing either triggers re-fetch with `offset=0`.
- **AC-C3**: Upload button visible only when managed storage AND admin AND `library_enabled`. Calls `POST /api/library/upload` per file. Shows progress bar. Refreshes grid on success.
- **AC-C4**: Upload 429 response shows a toast, does not crash.
- **AC-C5**: Delete `×` overlay rendered only when managed storage AND admin AND `delete_enabled`. Click shows `confirm()` dialog, then calls `DELETE /api/library/objects/{filename}`.
- **AC-C6**: Successful delete removes the thumbnail from the DOM and decrements the count display.

---

## Part D — Remove old code

### HTML to remove
- The entire `#panel-library` `<div>` (lines ~476–524 in current `index.html`).

### JS functions to remove
- `libraryFetchObjects()` — replaced by grid fetch logic
- `libraryUpload()` — replaced by grid upload logic
- `libraryDelete()` — replaced by grid delete logic
- `libraryMove()` — no longer exposed in UI (move is a storage internal)
- `initLibrary()` — replaced by grid init
- `updateLibraryVisibility()` — replaced by feature-flag checks in grid render
- `showBrowseModal()` — replaced by `#panel-grid`
- `apiGetRandom()` — replaced by explicit grid selection
- `handleBrowse()` (the old version that calls `showBrowseModal`) — replaced by new `handleBrowse()` that calls `setViewState("grid")` + fetch
- Library-specific variables: `libraryCursor`, `libraryObjects`, `libraryCurrentOffset`, `libraryTotalInWindow`, `libraryTruncated`, `libraryFolderFilter`, `librarySearchDebounceTimer`

### JS functions to keep (used by unified grid)
- `getPaginationRange()` — reused for grid pagination
- `applyImageData()` — reused for detail view
- `handleNext()` / `handlePrev()` — rewritten for grid-based sequential navigation
- `initGestures()` — kept for swipe in detail view (swipe calls new `handleNext`/`handlePrev`)
- Toast system — kept
- Auth/admin system — kept

### Review mode removal
- Remove `initReviewMode()`, `loadReviewImage()`, `reviewList`, `reviewIndex`, `currentMode` (review/publish distinction).
- The concept of "review mode vs publish mode" is replaced by the grid → detail flow. There is only one mode now.
- `handleNext`/`handlePrev` no longer branch on `currentMode === "review"`.

### Acceptance Criteria

- **AC-D1**: `#panel-library` HTML block is fully removed from `index.html`.
- **AC-D2**: All JS functions listed above are removed. No references to them remain.
- **AC-D3**: `apiGetRandom()` is removed. No random image loading exists.
- **AC-D4**: `initReviewMode()`, `loadReviewImage()`, `reviewList`, `reviewIndex` are removed. `currentMode` variable is removed.
- **AC-D5**: `showBrowseModal()` is removed. No dynamic modal creation for browsing.
- **AC-D6**: `getPaginationRange()` is preserved.
- **AC-D7**: Library API endpoints (`/api/library/*`) are **not touched** — they remain unchanged.

---

## Part E — Startup flow rewrite

Current startup (`DOMContentLoaded`):
1. Fetch `/api/config` → feature flags
2. `setModeFromConfig()` → set `currentMode` to `"publish"` or `"review"`
3. If publish mode: `apiGetRandom()` → load random image
4. If review mode: `initReviewMode()` → load review list + first image
5. `initLibrary()` → conditionally show library panel

New startup:
1. Fetch `/api/config` → feature flags, `storageProvider` (new field, see Part F)
2. Detect capabilities: `isManagedStorage = storageProvider === "managed"`, `isAdmin` (from admin cookie check), `libraryEnabled`, `deleteEnabled`
3. Initialize grid state: `gridOffset = 0`, `gridSort = "name"`, `gridOrder = "asc"`, `gridQ = ""`, `gridImages = []`, `gridCurrentIndex = -1`
4. `setViewState("grid")` → show grid panel
5. Fetch grid data → render thumbnails
6. Wire toolbar controls (search debounce, sort change, upload change, etc.)

The UI **starts in grid view** — no random image, no review list. The operator sees their image library immediately.

### Acceptance Criteria

- **AC-E1**: On `DOMContentLoaded`, after fetching `/api/config`, the UI calls `setViewState("grid")` and fetches the first page of images.
- **AC-E2**: No call to `apiGetRandom()` or `initReviewMode()` at startup.
- **AC-E3**: Grid toolbar controls are wired based on capabilities: search/sort/upload/delete hidden or shown per Part C rules.

---

## Part F — Backend: expose `storage_provider` in `/api/config`

The frontend needs to know whether the instance uses Dropbox or managed storage to decide which data source and controls to render.

**Change**: In `web/routers/config.py` (or wherever `/api/config` is served), add `"storage_provider": "dropbox" | "managed"` to the response JSON. Source the value from `config.storage.provider` (the `StorageProviderEnum`).

This is the **only backend change** in this item. All library API endpoints remain unchanged.

### Acceptance Criteria

- **AC-F1**: `GET /api/config` response includes `"storage_provider": "dropbox"` or `"storage_provider": "managed"` matching the instance's configured storage provider.
- **AC-F2**: Existing fields in `/api/config` response are unchanged (backwards-compatible addition).

---

## Non-Goals

- Folder tabs for archive/keep/remove (not needed in the publisher workflow)
- Drag-and-drop upload (file picker is sufficient for v1)
- Bulk select / bulk delete (single-image actions only for v1)
- Image preview lightbox with zoom (click goes to detail view, not a lightbox)
- Changes to the analyze/publish/keep/remove actions (those remain in the detail view)
- Changes to any library API endpoint (only the consuming UI changes)
- Move functionality in the grid (move is a storage internal, not user-facing)

## Quality Gates

- `ruff check` — zero violations in changed files
- `mypy` — zero errors
- `pytest` — all existing tests pass; new tests for `/api/config` `storage_provider` field
- Existing library API tests remain green and unchanged
- Manual verification: grid renders, thumbnail click loads detail, back-to-grid preserves state

## Related

- [PUB-031: Managed Storage Migration & Admin Library](archive/PUB-031_managed-storage-migration-admin-library.md) — original library API and UI
- [PUB-032: Admin Library — Sorting & Filtering](archive/PUB-032_library-list-sort-filter.md) — sort/filter/offset API this reuses
- [PUB-019: Swipe Gestures & Workflow Modes](archive/PUB-019_swipe-workflow-modes.md) — swipe navigation this supersedes
