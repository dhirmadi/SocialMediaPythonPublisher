# PUB-033 Implementation Handoff — Unified Image Browser

**Status**: Hardened → Ready for implementation
**Spec**: `docs_v2/roadmap/PUB-033_unified-image-browser.md`

---

## Implementation Order

Implement stories in this order (each depends on the previous):

1. **Story F**: Backend — expose `storage_provider` in `/api/config/features`
2. **Story D**: Remove old code (library panel HTML, old JS functions, review mode)
3. **Story A**: Grid view panel (HTML + data fetching + rendering + pagination)
4. **Story B**: View state machine (grid ↔ detail transitions, next/prev navigation)
5. **Story C**: Search, sort, upload, delete in grid toolbar
6. **Story E**: Startup flow rewrite (DOMContentLoaded → grid view)

Story F is the only backend change and should land first so the frontend can consume `storage_provider`. Story D (removal) should happen early to avoid editing code that will be deleted. Stories A–C build up the new UI. Story E rewires startup.

---

## Files to Modify

| File | What Changes |
|------|-------------|
| `publisher_v2/src/publisher_v2/web/app.py` | Add `storage_provider` to `api_get_features_config` response (Story F) |
| `publisher_v2/src/publisher_v2/web/templates/index.html` | Remove `#panel-library`, remove old JS, add `#panel-grid` HTML, new JS for grid/detail state machine, toolbar, startup (Stories A–E) |

No changes to `web/routers/library.py` or any other backend file.

---

## Files to Create

None (all changes are in existing files).

---

## Test Targets

### Backend (Story F)

| Test | Location | What to Assert |
|------|----------|----------------|
| `test_features_config_includes_storage_provider_managed` | `publisher_v2/tests/web/test_features_config.py` (new or extend existing) | `GET /api/config/features` returns `"storage_provider": "managed"` when `config.managed` is set |
| `test_features_config_includes_storage_provider_dropbox` | same | `GET /api/config/features` returns `"storage_provider": "dropbox"` when `config.dropbox` is set |
| `test_features_config_existing_fields_unchanged` | same | All existing keys (`analyze_caption_enabled`, `publish_enabled`, etc.) still present |

### UI tests (Stories A–E)

| Test | Location | What to Assert |
|------|----------|----------------|
| `test_html_contains_panel_grid` | `publisher_v2/tests/web/test_library_ui.py` (update) | `id="panel-grid"` present in rendered HTML |
| `test_html_no_panel_library` | same (update) | `id="panel-library"` no longer present |
| `test_html_no_apiGetRandom` | same (update) | `apiGetRandom` not in rendered JS |
| `test_html_no_showBrowseModal` | same (update) | `showBrowseModal` not in rendered JS |

The existing tests in `test_library_ui.py` assert the *old* panel exists — these must be **rewritten** (not just deleted) to assert the *new* grid panel. The existing tests in `test_library_feature_flag.py` are config-level and remain unchanged.

---

## Mock Boundaries

| Boundary | How to Mock |
|----------|------------|
| `WebImageService.config` | Fixture that sets `config.managed` or `config.dropbox` to control `storage_provider` |
| `/api/library/objects` | Not needed in unit tests (existing endpoint, tested separately) |
| `/api/images/list` | Not needed (existing endpoint) |
| Admin state | Set `WEB_AUTH_TOKEN` env var in fixture |

---

## Key Design Decisions

1. **`storage_provider` goes in `/api/config/features`** — not a new endpoint. It's a single field addition to the existing features config response. The frontend already fetches this endpoint at startup. Derive it from `config.managed is not None` → `"managed"`, else `"dropbox"`.

2. **Grid is a static HTML panel, not a dynamic modal** — `#panel-grid` is rendered server-side in the template (like `#panel-library` was). JS toggles its `hidden` class. This is consistent with the existing architecture.

3. **Two-path data fetching** — the grid fetch function branches on `storageProvider`:
   - `"managed"` → `GET /api/library/objects?limit=24&offset=...&sort=...&order=...&q=...`
   - `"dropbox"` → `GET /api/images/list` (cached 60s, client-side slicing)

4. **`gridImages` array** — stores the current page's filenames. `gridCurrentIndex` tracks which image is selected for detail view. This enables sequential next/prev without random jumps.

5. **Review mode is fully removed** — `currentMode`, `reviewList`, `reviewIndex`, `initReviewMode`, `loadReviewImage` all go away. The grid replaces the concept of "review mode". In the new model, there's only grid view and detail view.

6. **`apiGetRandom()` is fully removed** — no random image selection at startup or elsewhere. The UI starts in grid view.

7. **Existing library API is untouched** — all endpoints in `web/routers/library.py` remain exactly as they are. The grid consumes them; the old panel that also consumed them is removed.

8. **Existing tests need rewriting, not deletion** — `test_library_ui.py` tests assert `panel-library` exists. These should be rewritten to assert `panel-grid` exists and `panel-library` does not. This is a genuine change in expected behavior, not a test being "wrong".

---

## Implementation Command

```
/implement docs_v2/roadmap/PUB-033_handoff.md
```

---

## Potential Gotchas

1. **`index.html` is ~2200 lines** — the file is large. Be surgical: remove the `#panel-library` HTML block first, then remove the JS functions, then add new code. Don't try to rewrite the whole file.

2. **CSS for `.browse-grid` already exists** — it was added for the browse modal. It should work for the new grid panel without changes. Verify it still applies since the grid is no longer inside a modal dialog.

3. **`handleNext`/`handlePrev` currently branch on `currentMode`** — after removing review mode, these functions simplify to only the grid-based path. Make sure swipe gestures still call them correctly.

4. **The browse button (`#btn-browse`)** — currently it's hidden by default and shown by JS based on feature flags. In the new model, it should always be visible (it's the main entry point). But on startup, the grid is already shown, so the browse button acts as a "back to grid" when in detail view.

5. **`browseImageList` and `browseListTimestamp`** — these exist for the old Dropbox browse cache. Reuse them for the Dropbox path in the new grid. For managed storage, the grid data comes fresh from the API on each page fetch.

6. **The `/api/images/{filename}` endpoint** — this is what loads the full-size image + metadata for detail view. It works for both Dropbox and managed storage. No changes needed.
