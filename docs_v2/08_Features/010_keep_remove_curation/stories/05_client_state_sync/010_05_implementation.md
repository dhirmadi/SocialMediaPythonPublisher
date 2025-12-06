# Implementation Story: 05_client_state_sync

This story covers the client-side state synchronization defined in 010_05_plan.yaml.

## Context
When an image is curated (Kept or Removed), it is moved on the server. If the client is in "Review Mode" (sequential list), the local list of filenames (`reviewList`) becomes stale. If the user navigates back, the app attempts to load the moved file, resulting in a 404.

## Plan Execution

### 1. Update Frontend JS (`index.html`)
*   **Helper**: Added `removeFromReviewList(filename)` function to:
    *   Find the index of the curated filename.
    *   Remove it from `reviewList`.
    *   Adjust `reviewIndex` so that the "current" pointer remains valid (pointing to the *next* image which shifted into the current slot, or the end of the list).
    *   Update the position indicator (e.g. "5 / 99" -> "5 / 98").
*   **Integration**: Updated `apiKeep` and `apiRemove` to call `removeFromReviewList` upon success, *before* loading the next image.

## Verification
*   **Manual**:
    *   Load Review Mode.
    *   Keep/Remove an image.
    *   Verify list count decreases.
    *   Verify navigation (Next/Prev) skips the moved image.

