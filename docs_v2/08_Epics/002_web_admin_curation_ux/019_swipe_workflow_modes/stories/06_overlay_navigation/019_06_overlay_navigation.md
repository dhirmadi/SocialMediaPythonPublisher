# Story: Overlay Navigation Buttons

**Feature ID:** 019
**Story ID:** 019-06
**Name:** overlay_navigation
**Status:** Shipped
**Date:** 2025-12-06
**Parent Feature:** 019_swipe_workflow_modes

## Summary
Move the "Previous" and "Next" buttons from the bottom control panel to become overlays on the image container. This aligns the click navigation with the swipe gestures visually and ergonomically.
- **Previous:** Overlay on the left side (approx 5-10% width).
- **Next:** Overlay on the right side (approx 5-10% width).
- **Appearance:** Minimalist arrows (`<` and `>`) or chevrons, vertical centering, full height clickable area preferred.

## Scope
- Modify `index.html` structure to move buttons inside `.image-container`.
- Update CSS to position them absolutely over the image.
- Update button text/icons to be concise (`<`, `>`).
- Ensure "Previous" button visibility logic (hidden in Publish mode) still works.
- Ensure the old control bar layout handles the removal of these buttons gracefully.

## Acceptance Criteria
- "Previous" button is an overlay on the left side of the image.
- "Next" button is an overlay on the right side of the image.
- Buttons span a vertical strip (user suggested 5% width) to act as touch/click targets.
- Visual style is an overlay (e.g., semi-transparent or visible on hover) with arrow indicators.
- Functionality (click to nav) remains unchanged.
- "Previous" is hidden when in Publish Mode.

## Technical Notes
- `.image-container` needs `position: relative` (already added in Story 04/05).
- Buttons need `position: absolute`, `top: 0`, `bottom: 0`, `z-index: 10`.
- Use flexbox or centering for the arrow text within the button.

