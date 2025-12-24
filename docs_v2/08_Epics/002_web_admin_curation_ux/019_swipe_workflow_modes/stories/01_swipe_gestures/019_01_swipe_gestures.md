# Story: Swipe Gestures

**Feature ID:** 019
**Story ID:** 019-01
**Name:** swipe_gestures
**Status:** Shipped
**Date:** 2025-12-06
**Parent Feature:** 019_swipe_workflow_modes

## Summary
Implement touch swipe gestures on the main image container in the web UI. This is a frontend-only change (mostly) that maps swipe actions to the existing "Next" button functionality.

## Scope
- Add `touchstart` and `touchend` event listeners to `.image-container`.
- Implement basic swipe detection logic (threshold ~50px).
- Map "Swipe Left" to the "Next Image" action (currently `apiGetRandom`).
- Add visual feedback (CSS transform/opacity) during/after swipe.
- Ensure "Swipe Right" is ignored for now (as we default to Publish mode which has no Previous).

## Out of Scope
- Mode toggling (Story 03).
- Sequential navigation (Story 02/03).

## Acceptance Criteria
- Given I am on a mobile device, when I swipe left on the image, then the next random image loads.
- Given I swipe right, then nothing happens (for now).
- Given I swipe, the image container visually reacts (e.g., slides or fades) to acknowledge the gesture.
- Desktop "Next" button continues to work.

## Technical Notes
- Use `e.changedTouches[0].screenX` for delta calculation.
- Add CSS class `.swiping-left` for animation.

