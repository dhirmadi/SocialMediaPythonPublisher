# PUB-036: Upload Queue with Client-Side Rate Limiting

**GitHub Issue:** #60
**Category:** Web UI
**Priority:** P1
**Effort:** S
**Dependencies:** PUB-031, PUB-033
**Status:** Done

## Problem

When uploading multiple images via the grid toolbar, the frontend processes files sequentially but breaks on the first failure (e.g., 429). There is no per-file progress, no retry mechanism, and no visual queue showing upload status per file. Selecting more than 10 files exceeds the server's rate limit (10/60s), causing uploads beyond the limit to fail permanently.

## Solution

A frontend-only enhancement that adds a visual upload queue with per-file status indicators, client-side rate limiting to stay within server limits, and auto-retry on 429 responses.

## Acceptance Criteria

### AC-1: Visual upload queue panel
- When multiple files are selected, show a queue panel below the grid toolbar with per-file rows
- Each row shows: filename (truncated), status indicator, and progress
- Status indicators: Queued, Uploading (with progress bar), Done, Failed (with retry button)
- Queue panel appears when files are selected, auto-hides after all uploads complete (with delay)

### AC-2: Client-side throttling
- Process uploads sequentially (one file at a time)
- Track upload timestamps and enforce max ~8 uploads per 60-second window (headroom below server's 10/min)
- If rate limit would be exceeded, wait until enough time has elapsed before starting the next upload

### AC-3: Auto-resume on 429
- If server returns 429, pause the queue and auto-retry the failed file after a backoff period (5-10 seconds)
- Use exponential backoff: 5s first retry, 10s second retry
- After 3 consecutive 429s on the same file, mark it as failed with retry button
- Do NOT abandon remaining files in the queue on a single 429

### AC-4: Grid refresh on completion
- When all uploads finish (or all remaining are failed), refresh the grid to show new images
- Grid offset resets to page 1 to show the newly uploaded images

### AC-5: Backward compatibility
- The existing single-file upload progress bar is replaced by the new queue UI
- The upload button and file input remain unchanged
- Server-side rate limit in `library.py` is NOT modified

## Implementation Notes

- **Frontend-only change** in `publisher_v2/src/publisher_v2/web/templates/index.html`
- Replace the existing `gridUploadInput` change handler (lines ~1872-1888)
- Replace `handleGridUpload()` with queue-aware upload logic
- The old `#grid-upload-progress` bar is replaced by per-file progress in queue items
- Upload queue state: array of `{file, name, status, progress, retries, error}` objects
- Client-side rate limiter: track `uploadTimestamps[]`, check count within last 60s before each upload

## Non-goals

- No drag-and-drop (future enhancement)
- No upload cancellation (keep scope minimal)
- No server-side changes
