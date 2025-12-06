# Story: Automatic Mode Switching

**Feature ID:** 019
**Story ID:** 019-05
**Name:** automatic_mode_switching
**Status:** Proposed
**Date:** 2025-12-06
**Parent Feature:** 019_swipe_workflow_modes

## Summary
Remove the manual "Publish vs Review" mode toggle. Instead, automatically determine the mode based on the `publish_enabled` feature flag.
- If `publish_enabled` is **True**: Force **Publish Mode** (Random order, Next only).
- If `publish_enabled` is **False**: Force **Review Mode** (Sorted order, Next/Prev).

## Scope
- Remove HTML for the `.mode-toggle` buttons in `index.html`.
- Remove JS logic for `switchMode` and `localStorage` persistence of mode.
- Update JS initialization to set `currentMode` derived from `featureConfig.publish_enabled`.
- Ensure UI updates (Previous button visibility, Position Indicator) reflect this automatic mode.

## Acceptance Criteria
- The "Publish Mode / Review Mode" toggle buttons are removed from the UI.
- When `publish_enabled` is true (default), the app loads in Publish Mode (Random images, no Prev button).
- When `publish_enabled` is false (e.g. via env var), the app loads in Review Mode (Sorted images, Prev button visible).
- `localStorage` "pv2_mode" is ignored/cleared.

## Technical Notes
- `fetchFeatureConfig` is already called early in `initLayout`. Use its result to set `currentMode`.
- `updateModeUI` should be simplified to just handle button states, not toggle button classes.

