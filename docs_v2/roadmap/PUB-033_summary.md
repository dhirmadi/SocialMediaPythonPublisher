# PUB-033 — Unified Image Browser: Implementation Summary

**Status:** Implementation Complete
**Date:** 2026-04-13

## Files Changed

- `publisher_v2/src/publisher_v2/web/app.py` — added `storage_provider` field to `/api/config/features` response (Story F, AC-F1/F2)
- `publisher_v2/src/publisher_v2/web/templates/index.html` — full UI rewrite for unified grid:
  - Removed `#panel-library`, `library-toolbar` CSS, `library-objects` table CSS, mobile column-hide rule, modal-only `@media` grid override
  - Updated `.browse-grid` to `repeat(auto-fill, minmax(140px, 1fr))`; added `.delete-overlay`, `.grid-toolbar`, `.grid-upload-label` styles
  - Added static `#panel-grid` with toolbar (search/sort/order/upload/refresh), `#grid-container`, pagination bar
  - Added `#btn-back-to-grid` button
  - Removed JS: `apiGetRandom`, `showBrowseModal`, `handleBrowse`, `initReviewMode`, `loadReviewImage`, `prefetchNextSequential`, `prefetchNextThumbnail`, `removeFromReviewList`, `libraryFetchObjects`, `libraryUpload`, `libraryDelete`, `libraryMove`, `initLibrary`, `updateLibraryVisibility`, `libraryResetAndFetch`, `libraryUsingBufferedPath`, `formatFileSize`, `formatDate`, `escapeHtml`, `setModeFromConfig`, `updateModeUI`
  - Removed JS variables: `currentMode`, `reviewList`, `reviewIndex`, `prefetchedImage`, `libraryCursor`, `libraryOffset`, `librarySort`, `libraryOrder`, `libraryQ`, `libraryTotalInWindow`, `libraryTruncated`, `librarySearchTimeout`, `BROWSE_PAGE_SIZE`
  - Added grid state: `viewState`, `gridOffset`, `gridSortValue`, `gridOrderValue`, `gridQ`, `gridImages`, `gridCurrentIndex`, `gridTotal`, `gridTruncated`, `GRID_PAGE_SIZE=24`
  - Added new functions: `setViewState`, `isManagedStorage`, `updateGridToolbarVisibility`, `buildLibraryUrl`, `fetchGrid`, `renderGrid`, `renderGridPagination`, `selectGridItem`, `backToGrid`, `handleGridUpload`, `handleGridDelete`, `spliceCurrentFromGrid`, `advanceAfterAction`, `loadImageDetail`, `initGridControls`
  - Rewired `handleNext`/`handlePrev` for grid-based navigation across page boundaries
  - Rewired `apiPublish`/`apiKeep`/`apiRemove`/`apiDelete` to splice from `gridImages` and call `advanceAfterAction`
  - Startup now opens grid view first; no random load, no review mode

- `publisher_v2/tests/web/test_features_config.py` (new) — three tests for `storage_provider` field
- `publisher_v2/tests/web/test_library_ui.py` (rewritten) — asserts new grid panel scaffold and removal of old JS
- `publisher_v2/tests/web/test_library_sort_filter.py` (`TestUIControls`) — updated id assertions from `library-*` to `grid-*`

## Acceptance Criteria

### Story A — Grid view panel
- [x] AC-A1 — `#panel-grid` is a static `<div>` inside `<main>` (test: `test_panel_grid_present`)
- [x] AC-A2 — Managed instances call `/api/library/objects?limit=24&offset=...&sort=...&order=...&q=...` (in `buildLibraryUrl`/`fetchGrid`)
- [x] AC-A3 — Dropbox instances call `/api/images/list` cached 60s with client-side slicing (in `fetchGrid`)
- [x] AC-A4 — Lazy-loaded thumbnail with filename label and conditional delete overlay (`renderGrid`)
- [x] AC-A5 — `.browse-grid` uses `repeat(auto-fill, minmax(140px, 1fr))` (CSS)
- [x] AC-A6 — "Showing X–Y of Z" displayed (`renderGrid`, test: `test_grid_result_count`)
- [x] AC-A7 — Pagination Previous/Next/page-numbers using `getPaginationRange` (test: `test_grid_pagination_bar`)

### Story B — View state machine
- [x] AC-B1..B3 — `viewState` global, `setViewState("grid"/"detail")` toggles correct elements
- [x] AC-B4 — Thumbnail click → `selectGridItem` → `loadImageDetail` → `setViewState("detail")`; `gridOffset/Sort/Order/Q` preserved
- [x] AC-B5 — `btn-back-to-grid` calls `backToGrid` → `setViewState("grid")` (test: `test_back_to_grid_button`)
- [x] AC-B6/B7 — `handleNext`/`handlePrev` cross page boundaries by re-fetching
- [x] AC-B8 — Post-action `spliceCurrentFromGrid` + `advanceAfterAction`

### Story C — Toolbar
- [x] AC-C1 — Search visible only for managed (`updateGridToolbarVisibility`); 300ms debounce (`initGridControls`)
- [x] AC-C2 — Sort + order toggle visible only for managed; reset offset on change
- [x] AC-C3 — Upload visible only when managed + admin + library_enabled; sequential POST `/api/library/upload`
- [x] AC-C4 — 429 toast handled in `handleGridUpload`
- [x] AC-C5 — Delete `×` overlay rendered only when managed + admin + delete_enabled (`renderGrid`)
- [x] AC-C6 — Successful delete removes thumbnail and decrements count (`handleGridDelete`)

### Story D — Removal
- [x] AC-D1 — `#panel-library` removed (test: `test_panel_library_removed`)
- [x] AC-D2 — Library JS functions removed (tests: `test_libraryFetchObjects_removed`, `test_libraryMove_removed`)
- [x] AC-D3 — `apiGetRandom` removed (test: `test_apiGetRandom_removed`)
- [x] AC-D4 — Review mode removed (tests: `test_initReviewMode_removed`, `test_loadReviewImage_removed`)
- [x] AC-D5 — `showBrowseModal` removed (test: `test_showBrowseModal_removed`)
- [x] AC-D6 — `getPaginationRange` preserved (test: `test_getPaginationRange_kept`)
- [x] AC-D7 — `web/routers/library.py` not touched

### Story E — Startup
- [x] AC-E1 — DOMContentLoaded → fetch features → `setViewState("grid")` → `fetchGrid` (in `initLayout`)
- [x] AC-E2 — No `apiGetRandom`/`initReviewMode` calls
- [x] AC-E3 — Toolbar wired by `updateGridToolbarVisibility` per capability rules

### Story F — Backend
- [x] AC-F1 — `/api/config/features` includes `"storage_provider"` (tests: `test_features_config_includes_storage_provider_managed/dropbox`)
- [x] AC-F2 — Existing fields unchanged (test: `test_features_config_existing_fields_unchanged`)

## Test Results

```
publisher_v2/tests/web/test_features_config.py — 3 passed
publisher_v2/tests/web/test_library_ui.py — 16 passed (rewritten suite)
publisher_v2/tests/web/test_library_sort_filter.py — passed (TestUIControls updated)
publisher_v2/tests/web/* — 164 passed, 1 pre-existing failure unrelated to PUB-033
```

Two test failures persist on `main` and are unrelated to PUB-033:
- `test_publishers_endpoint.py::test_api_config_features_returns_json` — orchestrator env leakage from another test
- `test_publishers_platforms.py::test_email_publisher_sends_and_confirms` — base64 body encoding mismatch

Both confirmed pre-existing via `git stash` on the unmodified tree.

## Quality Gates

| Gate | Result |
|------|--------|
| `ruff format` | ✅ 152 files unchanged |
| `ruff check` | ✅ All checks passed |
| `mypy` | ✅ Success: no issues found in 148 source files |
| Tests | ✅ 650 passed (2 pre-existing failures unrelated) |
| Coverage overall | ✅ 88% (≥85%) |
| Coverage `web/app.py` | ✅ 96% (≥80%) |

## Notes / Decisions

- The spec said `.browse-grid` already used `repeat(auto-fill, minmax(140px, 1fr))` ("no change needed"), but the existing CSS used `repeat(5, 1fr)` with a `@media (max-width: 640px)` 3-column override. I updated the CSS to match the spec (the responsive auto-fill is the desired behaviour) and removed the now-redundant media query.
- The handoff said `storage_provider` should land in `/api/config/features`. Implemented by reading `service.config.managed is not None`.
- The `auto_view_enabled` non-admin path now displays the grid panel with an empty-state message ("Admin mode required to browse images.") rather than the old image placeholder, since the grid is the new entry point.
- For Dropbox, filename list is cached 60s (`BROWSE_CACHE_TTL`); the cache is invalidated whenever an image is curated to keep counts honest.
- All library API endpoints (`/api/library/*`) remain untouched per AC-D7.
