# PUB-044 — Configurable Grid Page Size

| Field | Value |
|-------|-------|
| **ID** | PUB-044 |
| **Category** | Web UI / UX |
| **Priority** | P2 |
| **Effort** | S |
| **Status** | Done |
| **Dependencies** | PUB-033 (Done — Unified Image Browser) |

---

## Problem

The image gallery grid is hardcoded to 24 items per page (`GRID_PAGE_SIZE = 24` in `index.html`). Users with large libraries must click through many pages to browse their images, while users with smaller libraries may prefer a denser view. There is no way to change the page size.

## Solution

Add a page-size selector (`<select>` element) to the grid toolbar that lets users choose between **10, 25, 50, and 100** images per page. The selection persists in `localStorage` so it survives page refreshes and sessions. All pagination logic uses the dynamic value instead of the hardcoded constant.

This is a **frontend-only change** — the backend `/api/library/objects` endpoint already accepts a `limit` query parameter.

---

## Scope

### In Scope

- **Page-size `<select>`** in the grid toolbar Find zone, after the sort order toggle
- **Options**: 10, 25, 50, 100
- **Default**: 25 (close to current 24, a rounder number)
- **Persistence**: `localStorage` key `pv2_grid_page_size`
- **Pagination**: all 12 references to `GRID_PAGE_SIZE` replaced with dynamic variable
- **UI lock**: selector added to `UPLOAD_LOCK_TARGETS` array (PUB-042 upload lock + delete queue lock)

### Out of Scope

- Infinite scroll / virtual scrolling
- Server-side page size validation or cap
- Responsive auto-sizing based on screen width
- Custom/arbitrary page sizes (only the 4 preset options)

---

## Implementation

### HTML

Add a `<select>` element with `id="grid-page-size"` in the `.toolbar-find` div, after `#grid-order-toggle`:

```html
<select id="grid-page-size" class="hidden" title="Items per page">
  <option value="10">10</option>
  <option value="25" selected>25</option>
  <option value="50">50</option>
  <option value="100">100</option>
</select>
```

The `hidden` class is removed when the grid panel opens (same pattern as `#grid-sort`).

### JavaScript

Replace `const GRID_PAGE_SIZE = 24;` with:

```javascript
const GRID_PAGE_SIZE_OPTIONS = [10, 25, 50, 100];
const GRID_PAGE_SIZE_DEFAULT = 25;
let gridPageSize = GRID_PAGE_SIZE_DEFAULT;
```

**Initialization** (in `openBrowseModal` or grid init):

```javascript
const stored = parseInt(localStorage.getItem("pv2_grid_page_size"), 10);
gridPageSize = GRID_PAGE_SIZE_OPTIONS.includes(stored) ? stored : GRID_PAGE_SIZE_DEFAULT;
document.getElementById("grid-page-size").value = String(gridPageSize);
```

**Change handler**:

```javascript
document.getElementById("grid-page-size").addEventListener("change", (e) => {
  gridPageSize = parseInt(e.target.value, 10);
  localStorage.setItem("pv2_grid_page_size", String(gridPageSize));
  gridOffset = 0;
  fetchGrid();
});
```

**All 12 references** to the old `GRID_PAGE_SIZE` constant become `gridPageSize`.

**UI lock**: Add `"grid-page-size"` to the `UPLOAD_LOCK_TARGETS` array.

---

## Acceptance Criteria

1. **AC-01**: The `.toolbar-find` zone contains a `<select id="grid-page-size">` with `<option>` values 10, 25, 50, 100. It is visible when the grid panel is open.
2. **AC-02**: Selecting a new page size sets `gridOffset = 0`, updates the `gridPageSize` variable, and calls `fetchGrid()`. The `limit` query parameter in the fetch URL matches the selected page size.
3. **AC-03**: On page-size change, `localStorage.setItem("pv2_grid_page_size", value)` is called with the selected value.
4. **AC-04**: On grid init, `localStorage.getItem("pv2_grid_page_size")` is read. If the value is one of `[10, 25, 50, 100]`, it is used. If absent, non-numeric, or not in the allowed set (e.g., `"30"`, `"abc"`, `null`), the default 25 is used.
5. **AC-05**: Pagination controls (prev/next disabled state, page number buttons, total pages calculation, result count) all use `gridPageSize` instead of the old `GRID_PAGE_SIZE` constant.
6. **AC-06**: The `"grid-page-size"` element ID is included in the `UPLOAD_LOCK_TARGETS` array, so the selector is disabled during upload and delete queue processing.
7. **AC-07**: The hardcoded `const GRID_PAGE_SIZE = 24` is removed. All 12 former references use `gridPageSize` instead.
8. **AC-08**: The current-image-page calculation (`Math.floor(idx / gridPageSize) * gridPageSize`) uses the dynamic value, so opening the grid jumps to the correct page for the current image.
9. **AC-09**: The `<select>` is styled consistently with the existing `#grid-sort` select (inherits `.grid-toolbar select` CSS rules — dark theme, compact, rounded border).

---

## Preview Mode

N/A — this is a frontend-only change. No backend or preview mode implications.

## Related

- [PUB-033: Unified Image Browser](archive/PUB-033_unified-image-browser.md)
- [PUB-042: Upload Queue Lock UI](archive/PUB-042_upload-queue-lock-ui.md) — selector must respect UI lock

---

2026-05-07 — Spec hardened for Claude Code handoff
