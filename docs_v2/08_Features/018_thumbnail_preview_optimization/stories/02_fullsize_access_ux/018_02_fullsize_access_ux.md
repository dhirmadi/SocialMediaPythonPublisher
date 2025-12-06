# Story: Full-Size Access UX

**Feature ID:** 018  
**Story ID:** 018-02  
**Name:** fullsize-access-ux  
**Status:** Proposed  
**Date:** 2025-12-06  
**Parent Feature:** 018_thumbnail_preview_optimization

## Summary

Add a "Full Size" button to the web UI that allows users to download or view the original full-resolution image. Since thumbnails are now displayed by default (Story 01), users need an explicit way to access the full-size image when needed (e.g., for detailed inspection before publishing).

## Scope

### In Scope
- Add "Full Size" / "Download" button to the web UI controls
- Wire button to open `temp_url` (full-resolution Dropbox link) in new tab
- Show/hide button based on image load state
- Add i18n support for button text via static config
- Update web UI text YAML with new button label

### Out of Scope (Deferred)
- Modal/lightbox for in-page full-size viewing (nice-to-have, low priority)
- Loading indicator for full-size images (browser handles this)
- Thumbnail preloading (Story 03)
- Configurable thumbnail sizes (Story 03)

## Acceptance Criteria

### AC1: Full-Size Button Visibility
- **Given** no image is loaded
- **When** the page is in its initial state
- **Then** the "Full Size" button is hidden

### AC2: Full-Size Button Appears
- **Given** an image is successfully loaded
- **When** the thumbnail is displayed
- **Then** the "Full Size" button becomes visible

### AC3: Full-Size Button Action
- **Given** an image is loaded and the "Full Size" button is visible
- **When** the user clicks the button
- **Then** the full-resolution image opens in a new browser tab
- **And** the original image URL (`temp_url`) is used

### AC4: Button Hidden on Placeholder
- **Given** an image load fails or placeholder is shown
- **When** `showImagePlaceholder()` is called
- **Then** the "Full Size" button is hidden

### AC5: I18n Support
- **Given** the `web_ui_text.en.yaml` static config
- **When** the button label is rendered
- **Then** it uses `buttons.fullsize` from config with fallback to "📥 Full Size"

### AC6: Mobile UX
- **Given** the web UI is viewed on a mobile device
- **When** the controls are displayed
- **Then** the "Full Size" button fits within the control layout without horizontal scrolling

## Technical Notes

### Files to Modify

1. **`publisher_v2/web/templates/index.html`**
   - Add `<button id="btn-fullsize">` to controls section
   - Add `handleFullSize()` function
   - Wire button in `initLayout()`
   - Show/hide button in `showImage()` and `showImagePlaceholder()`

2. **`publisher_v2/config/static/web_ui_text.en.yaml`**
   - Add `buttons.fullsize: "📥 Full Size"` entry

### HTML Changes

```html
<div class="controls">
  <button id="btn-next">{{ web_ui_text.buttons.next or "Next image" }}</button>
  <!-- NEW: Full size button -->
  <button id="btn-fullsize" class="secondary hidden">
    {{ web_ui_text.buttons.fullsize or "📥 Full Size" }}
  </button>
  <div id="admin-controls" class="controls admin-only hidden">
    <!-- existing admin buttons -->
  </div>
</div>
```

### JavaScript Changes

```javascript
// Add reference
const btnFullSize = document.getElementById("btn-fullsize");

// Add handler
function handleFullSize() {
  if (currentFullUrl) {
    window.open(currentFullUrl, "_blank");
  }
}

// Update showImage (from Story 01)
function showImage(thumbnailUrl, fullUrl, altText) {
  // ... existing code ...
  currentFullUrl = fullUrl;
  if (btnFullSize) {
    btnFullSize.classList.remove("hidden");
  }
}

// Update showImagePlaceholder (from Story 01)
function showImagePlaceholder(message) {
  // ... existing code ...
  currentFullUrl = null;
  if (btnFullSize) {
    btnFullSize.classList.add("hidden");
  }
}

// Wire in initLayout
function initLayout() {
  // ... existing code ...
  if (btnFullSize) {
    btnFullSize.addEventListener("click", handleFullSize);
  }
}
```

### CSS Considerations

The existing `.secondary` button style should work. Button uses `flex: 1 1 30%` which allows it to fit in the controls row. No CSS changes expected, but verify on mobile.

## Dependencies

- **Story 01 (Core Thumbnail Support)**: Must be completed first
  - `currentFullUrl` variable exists
  - `showImage()` accepts both thumbnail and full URLs
  - `temp_url` is stored for later use

## Definition of Done

- [ ] "Full Size" button added to HTML controls
- [ ] Button hidden by default, shown when image loads
- [ ] Click opens full-resolution image in new tab
- [ ] Button hidden when placeholder shown
- [ ] `web_ui_text.en.yaml` updated with button label
- [ ] Mobile layout verified (no horizontal scrolling)
- [ ] Manual testing on desktop and mobile browsers

