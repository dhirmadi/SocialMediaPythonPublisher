# Story: Overlay Download & Native Share

**Feature ID:** 019
**Story ID:** 019-07
**Name:** overlay_download
**Status:** Proposed
**Date:** 2025-12-06
**Parent Feature:** 019_swipe_workflow_modes

## Summary
Move the "Full Size" (Download) button to be an overlay on the image (bottom center/right). enhance the functionality on mobile devices to prefer saving to the Photo Library (via Native Share Sheet) instead of downloading to the Files app.

## Scope
- Move `#btn-fullsize` into `.image-container`.
- Style as a bottom-aligned overlay.
- Update `handleFullSize` JS function to:
  1.  Fetch the full-size image as a Blob.
  2.  Attempt to use `navigator.share` (Web Share API) to share the file. This triggers the iOS Share Sheet, which has a "Save Image" option (saves to Photos).
  3.  Fallback to `window.open` (or anchor download) if Share API is unavailable.

## Acceptance Criteria
- "Full Size" button is moved to an overlay position on the image.
- On supported mobile devices (iOS), clicking the button opens the Share Sheet (allowing "Save Image").
- On desktop or non-supporting browsers, it falls back to opening/downloading the file.
- Button visibility logic (hidden when no image) is preserved.

## Technical Notes
- **Web Share API Level 2** supports file sharing.
- Requires HTTPS (which is standard for this app usually, or localhost).
- `navigator.canShare({ files: [file] })` check is needed.
- Fetching the image blob might require CORS headers if not same-origin, but here it is same-origin (`/api/images/...`) or proxied via Dropbox link. If it's a direct Dropbox link, we might need to proxy the download through our backend to get the Blob for sharing, OR just rely on the link.
  - *Wait*: `currentFullUrl` currently is `data.temp_url` which is a direct Dropbox link.
  - *Issue*: Fetching a Blob from a Dropbox direct link in client-side JS might fail CORS.
  - *Solution*: If CORS prevents fetching the blob for sharing, we might have to stick to `window.open` or fallback. However, the user specifically wants "Save to Photos".
  - *Refinement*: We can try to use `navigator.share({ url: currentFullUrl })` first. iOS Share Sheet for a URL often gives "Save to Files", not "Save Image". To get "Save Image", we usually need to share the **File** object.
  - *Alternative*: If we can't fetch the blob client-side due to CORS, we can't use `navigator.share` with files.
  - *Check*: `temp_url` from Dropbox usually redirects.
  - *Pivot*: Let's try to fetch the blob. If it fails, fallback.

## UX
- Button Label: "📥" or "Save".
- Position: Bottom right or Bottom center.

