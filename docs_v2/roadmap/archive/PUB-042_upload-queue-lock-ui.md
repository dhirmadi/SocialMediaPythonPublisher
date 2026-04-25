# PUB-042 — Upload Queue: Lock UI During Active Uploads

| Field | Value |
|-------|-------|
| **ID** | PUB-042 |
| **Source** | [GH #66](https://github.com/dhirmadi/SocialMediaPythonPublisher/issues/66) |
| **Category** | Web UI / UX |
| **Priority** | P2 |
| **Effort** | S |
| **Status** | Done |
| **Dependencies** | PUB-036 (upload queue), PUB-037 (multi-select / bulk delete) |

---

## Problem

The upload queue is client-only state. If the user clicks a grid image, refreshes, switches sort/filter, or closes the browser tab while uploads are in flight, queued and in-progress uploads are silently abandoned.

There is no warning and no recovery path. The user has no way to know their uploads were just thrown away.

> Note on terminology: GH #66 references a "browse modal", but the upload queue actually lives inside the grid **panel** (`#panel-grid`). The user-facing equivalent of "closing the modal" is navigating away from the grid (clicking a grid item to view its detail) or closing the browser tab. This spec uses the panel and the `beforeunload` event as the lock points.

## Goals

1. Lock controls that would interrupt or destroy in-flight uploads while the queue is processing.
2. Show a clear "uploading — please wait" status message in the queue panel.
3. Confirm before allowing navigation away during active uploads (grid item click; tab close).
4. Restore all controls when the queue finishes (success or failure).
5. Never lock the UI when only failed/retryable entries remain — only active processing locks it.

## Non-goals

- Persisting queue state across page reloads (out of scope; client-side only).
- Modifying any server endpoint contracts.
- Adding a confirmation dialog for the existing "Dismiss queue" button (already an explicit user action).

## Solution

A single state-driven function `setUploadLockState(locked: boolean)` is called at the start and end of `processUploadQueue()`. When locked:

- The grid panel gains a CSS class `uploading-active` (visual cue, disables pointer-events on dim-styled controls).
- Controls are set to `disabled`:
  - `#grid-refresh-btn`
  - `#grid-sort`
  - `#grid-order-toggle`
  - `#grid-search`
  - `#grid-select-toggle`
  - `#grid-delete-selected`
- A status banner appears in the queue panel: "Uploading — please wait until all files are processed."
- A `beforeunload` listener is registered (returnValue triggers the browser's standard "are you sure?" prompt).
- `selectGridItem(filename)` first checks `uploadQueueProcessing`; if true, asks the user to confirm and aborts on cancel.

When unlocked:

- The CSS class is removed; all `disabled` attributes are cleared.
- The status banner is hidden.
- The `beforeunload` listener is removed.

## Acceptance Criteria

1. **AC-01**: A status banner element with id `upload-queue-status` is present inside the queue panel header. It is hidden by default and revealed only while the queue is processing.
2. **AC-02**: A function `setUploadLockState(locked)` exists and is called by `processUploadQueue()` at start (`true`) and end (`false`).
3. **AC-03**: While locked, the grid panel carries the CSS class `uploading-active`; while unlocked, the class is absent. The CSS contains a rule for `.uploading-active` that visually communicates the locked state.
4. **AC-04**: While locked, the following controls are `disabled`: `#grid-refresh-btn`, `#grid-sort`, `#grid-order-toggle`, `#grid-search`, `#grid-select-toggle`, `#grid-delete-selected`. While unlocked, none of these are disabled by the lock.
5. **AC-05**: While locked, a `beforeunload` listener is registered that prompts the browser to warn before tab/window close. While unlocked, no such listener is active.
6. **AC-06**: `selectGridItem(filename)` checks `uploadQueueProcessing` before navigating. When processing, it shows a confirmation dialog ("Uploads are still in progress…"); on cancel, navigation is aborted.
7. **AC-07**: When `processUploadQueue()` completes (success or with failures), `setUploadLockState(false)` is invoked unconditionally — the lock never leaks past queue completion.
8. **AC-08**: Failed entries that have not been retried do **not** lock the UI: `uploadQueueProcessing` is `false` while the user decides whether to retry.
9. **AC-09**: No regressions to the existing PUB-036/PUB-037 upload-queue behaviors (rate limiting, retry, auto-hide, dismiss button).

## Out of Scope

- Persisting upload progress across page reloads.
- Server-side resumable upload sessions.
- A general route-level navigation guard (no client router exists).

## Preview Mode

N/A — UI-only change inside the admin grid view; no publishing/archive side effects.

---

2026-04-25 — Spec drafted from GH #66 for direct implementation
