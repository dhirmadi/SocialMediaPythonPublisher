# Story: Position Indicator

**Feature ID:** 019
**Story ID:** 019-04
**Name:** position_indicator
**Status:** Proposed
**Date:** 2025-12-06
**Parent Feature:** 019_swipe_workflow_modes

## Summary
Add a visual indicator (e.g., "12 / 45") when in Review Mode to show progress through the folder.

## Scope
- Add HTML element for position display.
- Update JS to update this display when navigating in Review Mode.
- Hide this display in Publish Mode.

## Acceptance Criteria
- Review Mode shows "X / Y" where X is current index + 1 and Y is total count.
- Publish Mode hides this indicator.

## Technical Notes
- Simple text update in the rendering function.

