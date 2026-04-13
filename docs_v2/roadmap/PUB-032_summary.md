# PUB-032 — Admin Library Sorting & Filtering: Implementation Summary

**Status:** Implementation Complete
**Date:** 2026-04-13

## Files Changed
- `publisher_v2/src/publisher_v2/web/routers/library.py` — Added `_sanitize_filter`, `_get_scan_budget`, `_list_objects_buffered`; extended `LibraryListResponse` with `total_in_window`/`truncated`; updated `list_objects` endpoint with `q`, `sort`, `order`, `offset` params and path selection logic
- `publisher_v2/src/publisher_v2/web/templates/index.html` — Added search input, sort dropdown, order toggle, result count display, prev/next pagination buttons; refactored `libraryFetchObjects` for buffered path with debounced search
- `publisher_v2/tests/web/test_library_sort_filter.py` — 42 new tests covering all ACs
- `publisher_v2/tests/web/test_library_api.py` — Updated 2 existing tests for new default path routing (buffered path when no cursor)

## Acceptance Criteria
- [x] AC1 — Sort by name ascending (`test_sort_name_asc`)
- [x] AC2 — Sort by last_modified descending (`test_sort_last_modified_desc`, `test_sort_last_modified_asc`)
- [x] AC3 — Sort by size ascending (`test_sort_size_asc`, `test_sort_size_desc`)
- [x] AC4 — Invalid sort/order returns 400 (`test_invalid_sort_returns_400`, `test_invalid_order_returns_400`)
- [x] AC5 — Filter by q substring match (`test_filter_q_substring_match`, `test_filter_q_case_insensitive`)
- [x] AC6 — Empty/whitespace q treated as no filter (`test_filter_q_empty_returns_all`, `test_filter_q_whitespace_returns_all`)
- [x] AC7 — Path traversal sanitization (`test_filter_q_strips_path_traversal`, `test_filter_q_becomes_empty_after_strip`)
- [x] AC8 — Offset pagination (`test_offset_pagination`, `test_offset_with_limit`)
- [x] AC9 — Response includes total_in_window and truncated (`test_response_includes_total_in_window_and_truncated`)
- [x] AC10 — Offset beyond total returns empty (`test_offset_beyond_total_returns_empty`)
- [x] AC11 — Scan budget truncation (`test_scan_budget_truncation`)
- [x] AC12 — LIBRARY_SCAN_BUDGET env override (`test_scan_budget_env_override`, `test_scan_budget_invalid_env_fallback`)
- [x] AC13 — Legacy cursor path backwards compatibility (`test_legacy_cursor_path_no_new_params`, `test_cursor_response_has_zero_total`)
- [x] AC14 — Default no-params returns name-sorted ascending (`test_default_no_params_returns_name_asc`)
- [x] AC15 — UI search input, sort dropdown, order toggle (`test_ui_search_input_exists`, `test_ui_sort_controls_exist`)
- [x] AC16 — Result count display (`test_ui_result_count_container`)
- [x] AC17 — Previous/Next pagination buttons (`test_ui_prev_next_buttons`)
- [x] AC18 — Empty state "No objects match your filter." (implemented in JS, `libraryQ` check)
- [x] AC19 — Zero new ruff/mypy violations
- [x] AC20 — Full test coverage of all sort/filter/pagination scenarios

## Test Results
- 42 new tests in `test_library_sort_filter.py`: all passing
- 22 existing tests in `test_library_api.py`: all passing (2 updated for new routing)
- 609 total tests passing, 1 pre-existing failure (unrelated email test)

## Quality Gates
- Format: zero reformats needed
- Lint: zero violations
- Type check: zero errors (mypy)
- Tests: 609 passed, 1 pre-existing failure
- Coverage: 88% overall (library.py 75% — uncovered lines are pre-existing upload/delete/move inner functions from PUB-031)

## Notes
- Path selection logic: default (no cursor) now routes to buffered path per AC14, which provides identical name-sorted ascending order as PUB-031's S3 lexicographic listing
- Updated 2 existing tests in `test_library_api.py`: `test_list_objects_managed` now mocks `_list_objects_buffered` instead of `_list_objects_from_storage`; `test_list_objects_paginated` now sends a cursor param to trigger the legacy path
- UI "Load more" button is preserved for legacy cursor path; prev/next buttons appear for buffered path
- Search input uses 300ms debounce per spec
