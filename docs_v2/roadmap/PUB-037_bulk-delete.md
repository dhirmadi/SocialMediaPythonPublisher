# PUB-037: Multi-Select & Bulk Delete in Image Grid

**GitHub Issue:** #61
**Category:** Web UI
**Priority:** P2
**Effort:** S
**Dependencies:** PUB-033, PUB-036
**Status:** In Progress

## Problem

The image grid only supports single-image delete — each thumbnail requires an individual click on the `×` overlay plus a confirmation dialog. Cleaning up a library (duplicates, bad shots, test uploads) is tedious.

## Solution

Frontend-only change in `index.html`. Add a multi-select mode with bulk delete, reusing the upload queue pattern from PUB-036 for progress tracking.

## Acceptance Criteria

### AC-1: Multi-select toggle
- A "Select" toggle button in the grid toolbar enters/exits multi-select mode
- Only visible when `isManagedStorage() && isAdmin && featureConfig.delete_enabled`
- Escape key exits multi-select mode and clears all selections

### AC-2: Selection behavior
- In multi-select mode, clicking a thumbnail toggles its selection (highlighted border + checkbox overlay)
- A "Select all" button selects/deselects all visible thumbnails on the current page
- A counter shows "N selected" in the toolbar
- Normal single-click-to-detail is suppressed in multi-select mode

### AC-3: Bulk delete
- A "Delete selected (N)" button appears when ≥1 images are selected
- Single confirmation dialog: "Delete N images? This cannot be undone."
- Sequential `DELETE /api/library/objects/{filename}` calls (reuse rate limit pattern)
- Per-file progress in a delete queue panel (same visual pattern as upload queue)
- Removes deleted thumbnails from grid as each succeeds
- On completion, refreshes the grid

### AC-4: Feature gating
- Same gates as single delete: `isManagedStorage() && isAdmin && featureConfig.delete_enabled`
- No backend changes — reuses existing DELETE endpoint

## Non-Goals
- Bulk move, analyze, or publish
- Backend batch-delete endpoint
- Keyboard multi-select (Shift+click range select)

## Implementation Notes
- Selection state: `Set<string>` of filenames in JS
- Delete queue: mirror upload queue HTML/CSS/JS pattern from PUB-036
- Mobile: long-press not needed — toolbar toggle is sufficient
