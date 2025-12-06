# Overlay Download — Story Design

**Feature ID:** 019
**Story ID:** 019-07
**Parent Feature:** swipe_workflow_modes
**Design Version:** 1.0
**Date:** 2025-12-06
**Status:** Design Review
**Story Definition:** 019_07_overlay_download.md
**Parent Feature Design:** ../../019_design.md

## 1. Summary
This story moves the "Full Size" button to an overlay on the image and implements the Web Share API to facilitate saving images directly to the Photo Library on iOS.

## 2. Context & Assumptions
- **User Pain Point:** Downloading on iPhone goes to "Files", but user wants "Photos".
- **Solution:** iOS Share Sheet -> "Save Image" is the standard way to do this from a web page.
- **Constraints:** Dropbox temporary links might have CORS restrictions preventing client-side Blob fetching.

## 3. Requirements
### 3.1 Functional Requirements
- **SR1:** Move `#btn-fullsize` into `.image-container`.
- **SR2:** Style as a discreet overlay button (e.g., bottom-right corner).
- **SR3:** On click, attempt to download the image data (Blob).
- **SR4:** If Blob fetched and `navigator.share` supported, trigger Share Sheet.
- **SR5:** Fallback to opening URL in new tab if sharing fails or not supported.

### 3.2 Non-Functional Requirements
- **NFR1:** **Performance:** Don't block UI while fetching blob. Show "Downloading..." or spinner state.
- **NFR2:** **Error Handling:** Graceful fallback if CORS blocks blob fetch.

## 4. Architecture & Design (Delta)
### 4.1 Current vs. Proposed
- **Current:** `<div class="controls"><button id="btn-fullsize">...</button></div>` -> `window.open(url)`.
- **Proposed:**
  - HTML: Move button inside `.image-container`.
  - JS `handleFullSize`:
    ```javascript
    async function handleFullSize() {
      if (!currentFullUrl) return;
      setActivity("Downloading...");
      try {
        // Attempt to fetch blob for sharing
        const response = await fetch(currentFullUrl);
        const blob = await response.blob();
        const file = new File([blob], currentFilename || "image.jpg", { type: blob.type });

        if (navigator.canShare && navigator.canShare({ files: [file] })) {
          await navigator.share({
            files: [file],
            title: 'Image',
            text: currentFilename
          });
          setActivity("Shared successfully.");
        } else {
          throw new Error("Sharing not supported");
        }
      } catch (e) {
        console.log("Share failed/unsupported, falling back to open", e);
        window.open(currentFullUrl, "_blank");
        setActivity("Opened in new tab.");
      }
    }
    ```

### 4.2 Styling
- `.nav-overlay-bottom`: absolute, bottom 10px, right 10px (avoiding position indicator which is also bottom right... maybe move download to bottom left or center?).
- *Conflict*: Position indicator is currently `bottom: 10px; right: 10px`.
- *Resolution*: Move Position Indicator to `top: 10px; right: 10px` or `bottom: 10px; left: 10px`.
- *Better*: Move Position Indicator to **Top Right**. Move Download button to **Bottom Right**.
- *Button Style*: Round icon button (similar to standard floating action buttons).

## 5. Detailed Flow
1. User clicks Download icon.
2. JS fetches `currentFullUrl`.
3. If successful + Share API supported:
   - Invoke Share Sheet.
   - User selects "Save Image".
4. If failed (CORS) or API unsupported:
   - `window.open` (existing behavior).

## 6. Risks & Alternatives
- **Risk:** Dropbox CORS prevents `fetch(currentFullUrl)`.
  - **Mitigation:** Fallback is in place.
  - **Alternative:** Proxy download through backend `/api/images/{filename}/download` which streams the file. This guarantees CORS success.
  - **Decision:** Try direct fetch first. If CORS is an issue, we might need a backend proxy later. For now, try client-side. The `temp_url` usually allows GET.

## 7. Work Plan
- Task 1: Update HTML layout (move button, move position indicator).
- Task 2: Update CSS.
- Task 3: Update JS logic.

