# Story Summary: Automatic Mode Switching

**Feature ID:** 019
**Story ID:** 019-05
**Status:** Shipped
**Date Completed:** 2025-12-06

## Summary
Replaced the manual "Publish vs Review" toggle with automatic mode selection based on the server configuration.
- Removed the mode toggle UI elements (buttons).
- Removed `switchMode` logic and `localStorage` persistence.
- Implemented `setModeFromConfig` which sets the mode to "publish" (Random) if `publish_enabled` is true, or "review" (Sorted) if false.
- Ensured UI elements (Previous button, Position Indicator) update visibility correctly based on this derived mode.

## Files Changed
### Source Files
- `publisher_v2/src/publisher_v2/web/templates/index.html` — Removed toggle HTML/CSS; updated JS initialization logic.

### Documentation
- `docs_v2/08_Features/019_swipe_workflow_modes/stories/05_automatic_mode_switching/019_05_design.md`
- `docs_v2/08_Features/019_swipe_workflow_modes/stories/05_automatic_mode_switching/019_05_plan.yaml`

## Test Results
- Tests: N/A (Frontend logic verified manually by design).
- Coverage: N/A.

## Acceptance Criteria Status
- [x] AC1: Mode toggle buttons removed
- [x] AC2: Defaults to Publish Mode when enabled
- [x] AC3: Defaults to Review Mode when disabled
- [x] AC4: UI elements reflect mode

## Follow-up Items
- None.

