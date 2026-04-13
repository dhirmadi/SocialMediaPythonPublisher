# Implementation Handoff: PUB-032 — Admin Library Sorting & Filtering

**Hardened:** 2026-03-16
**Status:** Ready for implementation

## For Claude Code

### Test-first targets

| AC | Test file | Key test cases |
|----|-----------|----------------|
| AC1 | `publisher_v2/tests/web/test_library_sort_filter.py` | `test_sort_name_asc`, `test_sort_name_desc` |
| AC2 | `publisher_v2/tests/web/test_library_sort_filter.py` | `test_sort_last_modified_desc`, `test_sort_last_modified_asc` |
| AC3 | `publisher_v2/tests/web/test_library_sort_filter.py` | `test_sort_size_asc`, `test_sort_size_desc` |
| AC4 | `publisher_v2/tests/web/test_library_sort_filter.py` | `test_invalid_sort_returns_400`, `test_invalid_order_returns_400` |
| AC5 | `publisher_v2/tests/web/test_library_sort_filter.py` | `test_filter_q_substring_match`, `test_filter_q_case_insensitive` |
| AC6 | `publisher_v2/tests/web/test_library_sort_filter.py` | `test_filter_q_empty_returns_all`, `test_filter_q_whitespace_returns_all` |
| AC7 | `publisher_v2/tests/web/test_library_sort_filter.py` | `test_filter_q_strips_path_traversal`, `test_filter_q_becomes_empty_after_strip` |
| AC8 | `publisher_v2/tests/web/test_library_sort_filter.py` | `test_offset_pagination`, `test_offset_with_limit` |
| AC9 | `publisher_v2/tests/web/test_library_sort_filter.py` | `test_response_includes_total_in_window_and_truncated` |
| AC10 | `publisher_v2/tests/web/test_library_sort_filter.py` | `test_offset_beyond_total_returns_empty` |
| AC11 | `publisher_v2/tests/web/test_library_sort_filter.py` | `test_scan_budget_truncation` |
| AC12 | `publisher_v2/tests/web/test_library_sort_filter.py` | `test_scan_budget_env_override`, `test_scan_budget_invalid_env_fallback` |
| AC13 | `publisher_v2/tests/web/test_library_sort_filter.py` | `test_legacy_cursor_path_no_new_params`, `test_cursor_response_has_zero_total` |
| AC14 | `publisher_v2/tests/web/test_library_sort_filter.py` | `test_default_no_params_returns_name_asc` |
| AC15-18 | `publisher_v2/tests/web/test_library_sort_filter.py` | `test_ui_search_input_exists`, `test_ui_sort_controls_exist` (template snapshot / integration tests) |
| AC19 | (quality gate) | `uv run ruff check .` + `uv run mypy . --ignore-missing-imports --exclude=venv --exclude=env` |
| AC20 | All above | Aggregate pass |

### Mock boundaries

| External service | Mock strategy | Existing fixture |
|-----------------|---------------|------------------|
| S3 / boto3 (`list_objects_v2`) | Mock `storage.client.list_objects_v2` return value | See `tests/web/test_library_api.py::managed_app` fixture — reuse and extend |
| FastAPI test client | `TestClient(app)` with dependency overrides | Same as existing `managed_app` fixture |

### Files to modify

| Area | File | Changes |
|------|------|---------|
| Library router | `publisher_v2/src/publisher_v2/web/routers/library.py` | Add `q`, `sort`, `order`, `offset` params to `list_objects`; add `_list_objects_buffered`, `_sanitize_filter`, `_get_scan_budget`; extend `LibraryListResponse` with `total_in_window`, `truncated`; path selection logic |
| Web UI | `publisher_v2/src/publisher_v2/web/templates/index.html` | Add search input, sort dropdown, order toggle; replace "Load more" with prev/next in sort/filter mode; result count display; debounced search |

### Files to create

| Area | File |
|------|------|
| Tests | `publisher_v2/tests/web/test_library_sort_filter.py` |

### Key implementation details

**1. `_list_objects_buffered` inner function pattern:**

Follow the existing `_list_objects_from_storage` pattern: define a sync inner `_scan()` function, call via `asyncio.to_thread`. The inner function:
- Uses `storage.client.list_objects_v2()` (not the paginator) in a loop with `ContinuationToken`
- Passes `Delimiter='/'` to get immediate children only (matching existing behavior)
- Collects dicts with `key` (basename), `size` (int), `last_modified_raw` (datetime), `last_modified` (str)
- Stops at `scan_budget` collected image objects OR when S3 reports `IsTruncated: false`
- Sets `truncated = True` if budget was reached before listing completed

**2. Path selection in `list_objects` endpoint:**

```python
# Detect if new params are being used
use_buffered = (
    q is not None
    or sort != "name"
    or order != "asc"
    or offset > 0
    or cursor is None  # no cursor = new client = buffered path
)
use_legacy = not use_buffered and cursor is not None
```

When `use_legacy`: call existing `_list_objects_from_storage` (unchanged), set `total_in_window=0`, `truncated=False`.
When `use_buffered`: call `_list_objects_buffered`.

**3. `LibraryListResponse` is backwards-compatible:**

New fields have defaults (`total_in_window=0`, `truncated=False`), so existing clients parsing the old schema won't break.

**4. Sorting with `LastModified` as datetime:**

S3 returns `LastModified` as a Python `datetime` object from boto3. Keep the raw datetime for sorting, convert to ISO string only in the response object. Example:

```python
items.sort(key=lambda x: x["last_modified_raw"], reverse=(order == "desc"))
```

**5. UI JavaScript changes:**

- `libraryFetchObjects(append)` → refactor to accept `{offset, q, sort, order}` or read from DOM state
- New global state: `libraryOffset`, `librarySort`, `libraryOrder`, `libraryQ`, `libraryTotalInWindow`, `libraryTruncated`
- Search input: `<input type="text" id="library-search" placeholder="Filter by name...">`
- Sort dropdown: `<select id="library-sort">` with `Name | Date Modified | Size`
- Order button: `<button id="library-order-toggle">↑</button>` toggling between `asc`/`desc`
- Debounce: `setTimeout` pattern with 300ms delay on search input keyup

**6. Do NOT break existing test fixtures:**

The `managed_app` fixture in `tests/web/test_library_api.py` mocks `storage.client.list_objects_v2`. New tests should extend this mock to return objects with `Size` and `LastModified` fields (currently tests may not include these). Ensure existing test expectations still pass — the legacy cursor path must remain functional.

### Non-negotiables for this item

- [ ] **Preview mode**: Not affected — library is web-only, admin-only
- [ ] **Secrets**: No new credential exposure; `q` does not reach S3 as a key prefix
- [ ] **Auth**: Unchanged — `require_auth` + `require_admin` on all library endpoints
- [ ] **Coverage**: ≥80% on modified library router code

### Claude Code command

```text
/implement docs_v2/roadmap/PUB-032_library-list-sort-filter.md
```
