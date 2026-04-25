# PUB-042 — Upload Queue: Lock UI During Active Uploads — Implementation Summary

**Status:** Implementation Complete
**Date:** 2026-04-25
**Source:** [GH #66](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/66)

## Files Changed

- `publisher_v2/src/publisher_v2/web/templates/index.html` —
  - Added `#upload-queue-status` banner inside the queue panel header.
  - Added CSS for `.queue-status-banner` and `.uploading-active` lock visuals.
  - Added `setUploadLockState(locked)` JS function: toggles disabled on six grid controls, adds/removes `.uploading-active` on `#panel-grid`, shows/hides the banner, and registers/removes a `beforeunload` listener.
  - `processUploadQueue()` calls `setUploadLockState(true)` at start and `setUploadLockState(false)` in a `finally` block (lock cannot leak past completion).
  - `selectGridItem(fname)` now confirms before navigating away while `uploadQueueProcessing === true`.
- `publisher_v2/tests/web/test_upload_queue_lock_ui.py` — New file: 17 server-rendered HTML/JS smoke tests covering AC-01..AC-09.
- `docs_v2/roadmap/PUB-042_upload-queue-lock-ui.md` — Spec drafted from GH #66.
- `docs_v2/roadmap/PUB-042_plan.yaml` — Implementation plan.
- `docs_v2/roadmap/README.md` — Added "Web UI / UX" row for PUB-042.

## Acceptance Criteria

- [x] AC-01 — Status banner element with id `upload-queue-status`, hidden by default (`TestStatusBanner`)
- [x] AC-02 — `setUploadLockState(locked)` exists and is invoked at start/end of `processUploadQueue` (`TestLockStateFunction`)
- [x] AC-03 — `.uploading-active` class on `#panel-grid` and CSS rule defined (`TestUploadingActiveClass`)
- [x] AC-04 — Six grid controls receive `disabled` attribute via the lock chain (`TestControlsDisabled`)
- [x] AC-05 — `beforeunload` listener registered and removed by `setUploadLockState` (`TestBeforeUnloadGuard`)
- [x] AC-06 — `selectGridItem` confirms before navigation while processing (`TestNavigationGuard`)
- [x] AC-07 — Lock cleared in `finally` block — never leaks past queue completion (`test_ac07_lock_cleared_at_end_of_processing`)
- [x] AC-08 — Lock keyed on the boolean argument, not on queue state (`test_ac08_lock_uses_processing_flag_not_failed_count`)
- [x] AC-09 — No regression to PUB-036/PUB-037 queue features (`TestNoRegressions`)

## Test Results

- New PUB-042 tests: **17 passed**.
- Full suite (excluding one pre-existing flaky test unrelated to this change): **916 passed**.

## Quality Gates

- Format: ✅ (`uv run ruff format --check publisher_v2/`)
- Lint: ✅ (`uv run ruff check publisher_v2/`)
- Type check: ✅ (`uv run mypy publisher_v2/src/publisher_v2 --ignore-missing-imports` — 50 files clean)
- Tests: 916 passed, 1 deselected (see Notes), 0 failed
- Coverage: 88% overall (≥85% gate). PUB-042 changes are HTML/JS in `templates/index.html` — covered by smoke tests, not measured by `coverage.py`.

## Notes

- **Terminology:** GH #66 references a "browse modal", but this app has no real modal for browsing — the upload queue lives inside the grid **panel** (`#panel-grid`). The implementation uses the grid panel and the browser-native `beforeunload` event as lock points. The spec doc explains this mapping.
- **Design choice — `finally` block in `processUploadQueue`:** an unexpected exception inside one of the upload futures could otherwise leave the lock stuck on. Wrapping the loop in `try/finally` guarantees `setUploadLockState(false)` always runs.
- **Failed-only entries do not lock the UI** (AC-08): the lock is keyed on the boolean argument to `setUploadLockState`, not on queue contents. After `processUploadQueue` returns, the user is free to retry, dismiss, or leave even if some entries are in `failed` state.
- **Pre-existing unrelated test failure:** `publisher_v2/tests/web/test_web_service_coverage.py::TestAnalyzeAndCaptionSdCaptionFallback::test_falls_back_to_legacy_caption_on_sd_error` fails against the current working tree because an out-of-session edit to `publisher_v2/src/publisher_v2/web/service.py` changed the SD-error fallback to call `create_caption_from_analysis` instead of `create_caption`, but the test still mocks only the old method. This is **not caused by PUB-042** and should be addressed separately by updating the test mock to match the new fallback API.
- **Preview mode:** N/A — UI-only change, no side effects on preview path.
- **Backward compatibility:** all existing IDs preserved (`grid-refresh-btn`, `grid-sort`, etc.); existing PUB-036/PUB-037 behaviors unchanged (rate limiting, retry, auto-hide, dismiss, multi-select).
