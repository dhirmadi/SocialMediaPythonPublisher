# Story: Mode Toggle & Review Logic

**Feature ID:** 019
**Story ID:** 019-03
**Name:** mode_toggle_integration
**Status:** Shipped
**Date:** 2025-12-06
**Parent Feature:** 019_swipe_workflow_modes

## Summary
Add the UI toggle for "Publish" vs "Review" modes and implement the client-side logic to handle sequential navigation in Review Mode using the endpoints from Story 02.

## Scope
- Add HTML/CSS for Mode Toggle (Publish / Review).
- Implement JS `currentMode` state.
- Implement "Review Mode" logic:
  - Fetch list on enter.
  - Track current index.
  - "Next" -> index++, fetch specific filename.
  - "Prev" -> index--, fetch specific filename.
- Update Swipe Handler to call Prev on Swipe Right if in Review Mode.
- Persist mode in `localStorage`.
- Implement sequential prefetching in Review Mode.

## Out of Scope
- Position indicator (Story 04).

## Acceptance Criteria
- Clicking "Review" switches mode and loads the sorted list.
- In Review Mode, "Next" loads the next alphabetical image.
- In Review Mode, "Prev" (button or swipe right) loads the previous image.
- In Publish Mode, "Prev" is hidden/disabled.
- Reloading the page remembers the last selected mode.
- In Review Mode, the next image (N+1) is prefetched automatically.

## Technical Notes
- Add `btn-prev` to HTML (hidden by default).
- Handle end-of-list bounds (disable Next at end, Prev at start).
- **Prefetching:** Differentiate prefetch logic based on mode:
  - Publish Mode: Prefetch `random`.
  - Review Mode: Prefetch `list[currentIndex + 1]`.
