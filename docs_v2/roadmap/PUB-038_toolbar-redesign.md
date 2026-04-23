# PUB-038: Grid Toolbar Layout Redesign

**GitHub Issue:** #62
**Category:** Web UI
**Priority:** P2
**Effort:** S
**Dependencies:** PUB-033, PUB-036, PUB-037
**Status:** In Progress

## Problem

Grid toolbar controls are in a flat row with no logical grouping. Search, sort, upload, select, and refresh are jumbled together. Upload uses danger-red styling. The sort order toggle is oversized. Refresh sits on its own full-width row.

## Solution

Frontend-only restructure of the grid toolbar into two clear functional zones with modern visual hierarchy. No new functionality — purely layout and styling.

## Acceptance Criteria

### AC-1: Two-zone layout
- **Find zone** (left): search input + sort dropdown + compact order toggle
- **Actions zone** (right): upload button + refresh button
- Zones are visually distinct and flow left-to-right on desktop
- On mobile (<640px), zones stack vertically (find above actions)

### AC-2: Visual hierarchy
- Upload button uses primary gradient styling (not danger-red)
- Order toggle is a compact square icon button (not a wide bar)
- Refresh is a compact secondary/icon button beside upload
- Select mode toggle is subtle, positioned below or after actions
- Result count is muted metadata text, integrated below the toolbar

### AC-3: Preserve all functionality
- All existing element IDs preserved (no breaking changes)
- Search debounce, sort change, upload, refresh, select mode all work unchanged
- `updateGridToolbarVisibility()` logic unchanged
- Feature gating unchanged

### AC-4: Responsive design
- Desktop: two-zone side-by-side layout
- Mobile: zones stack, all controls remain usable
- Touch targets ≥44px on all interactive elements
- No horizontal scrolling

## Non-Goals
- New controls or features
- Backend changes
- JavaScript logic changes (beyond DOM reference updates if needed)
