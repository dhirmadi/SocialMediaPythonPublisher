# Story Summary: Overlay Navigation

**Feature ID:** 019
**Story ID:** 019-06
**Status:** Shipped
**Date Completed:** 2025-12-06

## Summary
Moved the "Previous" and "Next" navigation buttons from the control panel to become overlays on the image container.
- Added `.nav-overlay` CSS class for absolute positioning over the image.
- Moved `#btn-prev` and `#btn-next` elements inside `.image-container` in `index.html`.
- Styled buttons as transparent overlays (15% width for usability) on the left/right edges with simple `<` and `>` arrow indicators.
- Removed text label updates in `updateModeUI` since arrows are static.

## Files Changed
### Source Files
- `publisher_v2/src/publisher_v2/web/templates/index.html` — Updated HTML structure and CSS.

### Documentation
- `docs_v2/08_Epics/002_web_admin_curation_ux/019_swipe_workflow_modes/stories/06_overlay_navigation/019_06_design.md`
- `docs_v2/08_Epics/002_web_admin_curation_ux/019_swipe_workflow_modes/stories/06_overlay_navigation/019_06_plan.yaml`

## Test Results
- Tests: N/A (Frontend layout)
- Coverage: N/A

## Acceptance Criteria Status
- [x] AC1: Buttons positioned over image
- [x] AC2: Labels are < and >
- [x] AC3: Full height overlays
- [x] AC4: Logic preserved

## Follow-up Items
- None.

