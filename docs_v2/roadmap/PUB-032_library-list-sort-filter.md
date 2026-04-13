# PUB-032: Admin Library — Sorting & Filtering

| Field | Value |
|-------|-------|
| **ID** | PUB-032 |
| **Category** | Web UI / Storage |
| **Priority** | P1 |
| **Effort** | M |
| **Status** | Not Started |
| **Dependencies** | PUB-031 (Done) |

## Problem

The managed-storage Admin Library (`GET /api/library/objects` + panel in the web UI) lists images as a single flat stream with folder tabs and opaque cursor pagination. As libraries grow to hundreds or thousands of objects, operators cannot find a file quickly, compare by size or date, or narrow the list without paging through everything sequentially.

## Desired Outcome

1. **Filtering**: Admins can narrow the visible list by filename (case-insensitive substring). No path traversal or arbitrary S3 key injection.
2. **Sorting**: Admins can order the list by filename, last modified, or object size, ascending or descending.
3. **Web UI**: The library panel exposes filter inputs and sort controls; behavior matches the API contract.
4. **Backwards compatibility**: Existing clients that omit new query parameters get today's behavior exactly.

## Scope

### Strategy: Buffered Window

S3 has no server-side sort by metadata — listing is lexicographic by key only. True global sort across a large folder requires listing all keys then sorting in memory.

**This item uses the "buffered window" approach:**
1. On each `GET /api/library/objects` call, the backend scans up to `scan_budget` S3 keys (default 5000, configurable via `LIBRARY_SCAN_BUDGET` env var).
2. The scanned keys are filtered (by `q` substring match) and sorted (by `sort` + `order`) **in memory**.
3. The sorted/filtered result is then paginated using `offset`/`limit` (offset-based, not cursor-based — see migration note below).

**Trade-off**: For folders with fewer than `scan_budget` objects, sorting and filtering are globally correct. For folders exceeding the budget, results are sorted within the scanned window and the response includes `"truncated": true` so the UI can inform the operator.

### Pagination change: offset replaces cursor

The current `cursor`-based pagination (S3 `ContinuationToken`) is incompatible with server-side sort/filter — a cursor is only valid for the same S3 listing query and cannot carry sort state. This item replaces cursor pagination with `offset`/`limit`:

- `offset` (default 0): number of results to skip in the sorted/filtered window
- `limit` (default 50, max 200): number of results to return
- The `cursor` parameter is **still accepted** but **ignored** when `sort`, `order`, or `q` are present (backwards compatibility). When none of the new params are present and `cursor` is provided, the old cursor path is used (exact same behavior as PUB-031).
- The response model gains `total_in_window: int` (count of filtered objects in the scanned window) and `truncated: bool` (true if scan budget was reached before listing completed).

### API changes to `GET /api/library/objects`

New optional query parameters:

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `q` | `str \| None` | `None` | Case-insensitive substring filter on basename. Max 100 chars. Stripped of `/`, `\`, `..` for safety. |
| `sort` | `str` | `"name"` | Sort field: `name`, `last_modified`, `size`. Invalid values → 400. |
| `order` | `str` | `"asc"` | Sort direction: `asc`, `desc`. Invalid values → 400. |
| `offset` | `int` | `0` | Pagination offset into the sorted/filtered window. Min 0. |

Existing parameters (unchanged semantics):
| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `prefix` | `str` | `""` | Logical folder filter: `""`, `archive`, `keep`, `remove` |
| `limit` | `int` | `50` | Results per page (1–200) |
| `cursor` | `str \| None` | `None` | Legacy S3 continuation token (used only when no sort/filter/offset params present) |

**Response model** (`LibraryListResponse` extended):

```python
class LibraryListResponse(BaseModel):
    objects: list[LibraryObject]
    cursor: str | None = None          # populated only in legacy cursor path
    total_in_window: int = 0           # total matching objects in scanned window
    truncated: bool = False            # True if scan_budget was reached
```

### Backend implementation (`_list_objects_buffered`)

New helper function alongside existing `_list_objects_from_storage`:

1. Calls `list_objects_v2` with `Prefix` and `Delimiter='/'` in a loop, collecting up to `scan_budget` immediate-child image keys with their `Size` and `LastModified` metadata.
2. Applies `q` filter: `q.lower() in basename.lower()` (basename = key after last `/`).
3. Sorts by the requested field:
   - `name`: lexicographic on lowercase basename
   - `last_modified`: by S3 `LastModified` datetime
   - `size`: by S3 `Size` integer
4. Applies `offset` + `limit` slice to the sorted list.
5. Returns `objects`, `total_in_window` (count after filtering, before slicing), and `truncated` (whether the scan stopped at budget).

### Path selection logic

In the `list_objects` endpoint:

```
if any new param is non-default (q is not None, sort != "name", order != "asc", offset > 0):
    → use _list_objects_buffered (sort/filter path)
else if cursor is provided:
    → use existing _list_objects_from_storage (legacy cursor path)
else:
    → use _list_objects_buffered with defaults (sort by name asc, no filter)
```

This ensures:
- Clients using `cursor` from PUB-031 keep working (AC6)
- New clients get sort/filter automatically
- Default behavior (no params) is name-sorted ascending (matches S3 lexicographic order, so results are identical to PUB-031)

### Web UI changes (`index.html`)

Extend the library panel toolbar:

- **Search input**: text field bound to `q`, debounced 300ms, triggers re-fetch from offset 0
- **Sort dropdown**: `Name | Date Modified | Size` mapped to `sort` values
- **Order toggle button**: `↑` / `↓` toggling `asc`/`desc`
- **Result count**: show `"Showing {offset+1}–{offset+count} of {total_in_window}"` (or `"of {total_in_window}+"` when truncated)
- **Pagination**: "Previous" / "Next" buttons using `offset` arithmetic (replace "Load more" when sort/filter path is active)
- **Empty state**: "No objects match your filter." when `total_in_window == 0` and `q` is set

Existing folder filter dropdown, upload, delete, move controls remain unchanged.

### Security

- `q` parameter sanitized: strip `/`, `\`, `..`, null bytes. Max 100 characters. The filter operates on basenames only (after S3 key stripping), never on raw key prefixes.
- No new auth requirements — existing `require_auth` + `require_admin` on the endpoint.
- No credentials exposed in query strings or responses.

## Non-Goals

- Full-text search inside sidecar content or image metadata
- Cross-folder search in one query (each request remains scoped to one logical folder)
- Secondary index (database, Elasticsearch) for search
- Sort by custom metadata fields

## Acceptance Criteria

### Sorting

- **AC1**: `GET /api/library/objects?sort=name&order=asc` returns objects sorted by lowercase basename ascending.
- **AC2**: `GET /api/library/objects?sort=last_modified&order=desc` returns objects sorted by S3 `LastModified` descending (newest first).
- **AC3**: `GET /api/library/objects?sort=size&order=asc` returns objects sorted by S3 `Size` ascending (smallest first).
- **AC4**: `GET /api/library/objects?sort=invalid` returns 400 with JSON error body `{"detail": "..."}`. Same for `order=invalid`.

### Filtering

- **AC5**: `GET /api/library/objects?q=sunset` returns only objects whose basename contains "sunset" (case-insensitive).
- **AC6**: `GET /api/library/objects?q=` (empty string) is treated as no filter (all objects returned). `q` with only whitespace is also treated as no filter.
- **AC7**: `q` containing path traversal characters (`/`, `\`, `..`) has those characters stripped; the cleaned substring is used for matching. A `q` that becomes empty after stripping is treated as no filter.

### Pagination (offset-based)

- **AC8**: `GET /api/library/objects?offset=10&limit=5` skips the first 10 sorted/filtered results and returns 5.
- **AC9**: Response includes `total_in_window` (count of all matching objects in the scanned window) and `truncated` (bool).
- **AC10**: When `offset >= total_in_window`, response has `objects: []` (not an error).

### Scan budget

- **AC11**: When the scanned folder has more objects than `scan_budget`, the response has `truncated: true` and `total_in_window` reflects the count within the budget (not the true total).
- **AC12**: `LIBRARY_SCAN_BUDGET` env var overrides the default (5000). Invalid values fall back to the default.

### Backwards compatibility

- **AC13**: A request with only `prefix`, `cursor`, and `limit` (no `sort`, `order`, `q`, or `offset`) uses the legacy cursor-based S3 pagination path. Response has `cursor` populated (when more pages exist), `total_in_window: 0`, `truncated: false`.
- **AC14**: A request with no parameters at all returns name-sorted ascending results (same order as PUB-031's default S3 lexicographic listing).

### Web UI

- **AC15**: Library panel has a search input, sort dropdown, and order toggle button. Changing any control triggers a re-fetch from offset 0.
- **AC16**: Result count displays `"Showing X–Y of Z"` (or `"of Z+"` when truncated).
- **AC17**: "Previous" and "Next" pagination buttons appear when there are multiple pages. "Previous" is disabled at offset 0. "Next" is disabled when `offset + limit >= total_in_window`.
- **AC18**: Empty state "No objects match your filter." shown when `total_in_window == 0` and `q` is non-empty.

### Quality

- **AC19**: Zero new `ruff check` or `mypy` violations in touched files.
- **AC20**: Tests cover: each sort field + direction, filter matching + non-matching, path traversal sanitization, offset pagination, scan budget truncation, legacy cursor path, invalid parameter 400s, backwards-compatible default.

## Implementation Notes

### `_list_objects_buffered` design

```python
def _list_objects_buffered(
    service: WebImageService,
    prefix: str,
    q: str | None,
    sort: str,
    order: str,
    offset: int,
    limit: int,
    scan_budget: int,
) -> dict[str, Any]:
    """Scan up to scan_budget keys, filter, sort, paginate in memory."""
    # 1. Scan S3 with list_objects_v2 + Delimiter='/' in a loop
    # 2. Collect immediate-child image objects with key, Size, LastModified
    # 3. Apply q filter on basename
    # 4. Sort by field + direction
    # 5. Slice [offset:offset+limit]
    # 6. Return {objects, total_in_window, truncated}
```

Keep the existing `_list_objects_from_storage` function intact for the legacy cursor path.

### Scan budget tuning

- Default `5000` — covers ~95% of real instances (most have <1000 images)
- A Heroku request timeout is 30s; scanning 5000 keys via S3 takes ~2-5s for small objects
- `LIBRARY_SCAN_BUDGET` env var for operators with larger libraries (or to reduce for cost)

### `q` sanitization

```python
def _sanitize_filter(q: str | None) -> str | None:
    if not q:
        return None
    cleaned = q.replace("/", "").replace("\\", "").replace("..", "").replace("\x00", "")
    cleaned = cleaned.strip()[:100]
    return cleaned or None
```

### Sort key functions

```python
_SORT_KEYS = {
    "name": lambda obj: obj["key"].lower(),
    "last_modified": lambda obj: obj["last_modified_raw"],  # datetime object from S3
    "size": lambda obj: obj["size"],
}
```

Keep `LastModified` as a datetime internally for sort accuracy; convert to string only in the response serialization.

### UI debounce

Search input uses a 300ms debounce to avoid excessive API calls during typing. Sort/order changes trigger immediate re-fetch.

## Related

- [PUB-031: Managed Storage Migration & Admin Library](archive/PUB-031_managed-storage-migration-admin-library.md) — shipped list/upload/delete/move API and UI
- [PUB-024: Managed Storage Adapter](archive/PUB-024_managed-storage-adapter.md) — S3 protocol surface

---

*2026-03-16 — Spec hardened for Claude Code handoff*
