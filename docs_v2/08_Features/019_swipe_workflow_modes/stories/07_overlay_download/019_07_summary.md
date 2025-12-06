# Story Summary: Overlay Download & Native Share

**Feature ID:** 019
**Story ID:** 019-07
**Status:** Shipped
**Date Completed:** 2025-12-06

## Summary
Moved the "Full Size" download button to a bottom-right overlay on the image and enhanced its behavior for mobile devices.
- **UI:** Added `.download-overlay` CSS for a floating "📥" button in the bottom right corner.
- **UI:** Moved the Position Indicator to the **Top Right** corner to avoid overlap.
- **Functionality:** Updated `handleFullSize` to attempt using `navigator.share` with the file blob.
  - This allows iOS users to tap "Save Image" (to Photos) via the native Share Sheet.
  - Fallback to `window.open` (File Download) if sharing is unsupported or fails (e.g., due to CORS).

## Files Changed
### Source Files
- `publisher_v2/src/publisher_v2/web/templates/index.html` — Updated layout, CSS, and JS logic.

### Documentation
- `docs_v2/08_Features/019_swipe_workflow_modes/stories/07_overlay_download/019_07_design.md`
- `docs_v2/08_Features/019_swipe_workflow_modes/stories/07_overlay_download/019_07_plan.yaml`

## Test Results
- Tests: N/A (Frontend logic)
- Coverage: N/A

## Acceptance Criteria Status
- [x] AC1: Download button is an overlay
- [x] AC2: Position indicator moved
- [x] AC3: Native Share logic implemented
- [x] AC4: Fallback logic preserved

## Follow-up Items
- Monitor if Dropbox CORS headers allow client-side blob fetching in production. If not, a backend proxy route might be needed in a future story.

