# Story 018-02: Full-Size Access UX — Design

**Story ID:** 018-02  
**Design Version:** 1.1  
**Date:** 2025-12-06  
**Status:** Implemented  
**Parent Story:** 018_02_fullsize_access_ux.md

## 1. Overview

This story adds a "Full Size" button to the web UI, allowing users to access the original full-resolution image after Story 01 switches the default display to thumbnails.

## 2. UI Design

### 2.1 Button Placement

The button is placed in the main controls row, between "Next" and the admin controls:

```
┌─────────────────────────────────────────────────────────┐
│  ┌─────────────────────────────────────────────────┐    │
│  │            [Thumbnail Preview]                   │    │
│  └─────────────────────────────────────────────────┘    │
│                                                         │
│  ┌──────────┐  ┌──────────────┐  ┌─────────────────┐   │
│  │   Next   │  │ 📥 Full Size │  │  Admin Controls │   │
│  └──────────┘  └──────────────┘  └─────────────────┘   │
│                                                         │
│  Caption panel...                                       │
└─────────────────────────────────────────────────────────┘
```

### 2.2 Button States

| State | Button Visibility | Behavior |
|-------|-------------------|----------|
| Initial (no image) | Hidden | N/A |
| Image loading | Hidden | N/A |
| Image loaded | Visible | Opens `temp_url` in new tab |
| Image load error | Hidden | N/A |
| Placeholder shown | Hidden | N/A |

### 2.3 Styling

Uses existing `.secondary` button class:
- Background: `#111827`
- Text: `#e5e7eb`
- Border: `1px solid #374151`
- Flex: `1 1 30%` (same as other controls)

## 3. Implementation Details

### 3.1 HTML Addition

Insert button after "Next" button, before admin controls:

```html
<div class="controls">
  <button id="btn-next">
    {{ web_ui_text.buttons.next or "Next image" }}
  </button>
  <!-- NEW -->
  <button id="btn-fullsize" class="secondary hidden">
    {{ web_ui_text.buttons.fullsize or "📥 Full Size" }}
  </button>
  <div id="admin-controls" class="controls admin-only hidden">
    ...
  </div>
</div>
```

### 3.2 JavaScript Changes

**Add reference at top of script:**
```javascript
const btnFullSize = document.getElementById("btn-fullsize");
```

**Add handler function:**
```javascript
function handleFullSize() {
  if (currentFullUrl) {
    window.open(currentFullUrl, "_blank");
  }
}
```

**Update `showImage()` (builds on Story 01):**
```javascript
function showImage(thumbnailUrl, fullUrl, altText) {
  imagePlaceholder.classList.add("hidden");
  imgEl.src = thumbnailUrl;
  imgEl.alt = altText || "Image";
  imgEl.classList.remove("hidden");
  
  currentFullUrl = fullUrl;
  // NEW: Show full-size button
  if (btnFullSize) {
    btnFullSize.classList.remove("hidden");
  }
}
```

**Update `showImagePlaceholder()` (builds on Story 01):**
```javascript
function showImagePlaceholder(message) {
  if (imgEl) {
    imgEl.src = "";
    imgEl.classList.add("hidden");
  }
  if (imagePlaceholder) {
    const fallback = TEXT.placeholders?.image_empty || "No image loaded yet.";
    imagePlaceholder.textContent = message || fallback;
    imagePlaceholder.classList.remove("hidden");
  }
  currentFullUrl = null;
  // NEW: Hide full-size button
  if (btnFullSize) {
    btnFullSize.classList.add("hidden");
  }
}
```

**Wire in `initLayout()`:**
```javascript
function initLayout() {
  btnNext.addEventListener("click", apiGetRandom);
  // NEW: Wire up full-size button
  if (btnFullSize) {
    btnFullSize.addEventListener("click", handleFullSize);
  }
  // ... rest unchanged
}
```

### 3.3 Static Config Update

**File:** `publisher_v2/config/static/web_ui_text.en.yaml`

Add under `buttons` section:
```yaml
buttons:
  next: "Next image"
  analyze: "Analyze & caption"
  publish: "Publish"
  admin: "Admin"
  logout: "Logout"
  keep: "Keep"
  remove: "Remove"
  fullsize: "📥 Full Size"  # NEW
```

## 4. Edge Cases

### 4.1 Button Click Without URL
If `currentFullUrl` is null (defensive), the handler does nothing:
```javascript
function handleFullSize() {
  if (currentFullUrl) {  // Guard
    window.open(currentFullUrl, "_blank");
  }
}
```

### 4.2 Popup Blocked
Some browsers may block the `window.open()` call. This is acceptable behavior — the user can allow popups or right-click to open in new tab.

### 4.3 Admin Mode
The "Full Size" button is always visible when an image is loaded, regardless of admin mode. Viewing full-size images is not a privileged operation (same as clicking the image directly in the current implementation).

## 5. Mobile Considerations

### 5.1 Layout
Existing flex layout (`flex: 1 1 30%`) with `flex-wrap: wrap` handles narrow screens:
- On wide screens: buttons in single row
- On narrow screens: buttons wrap to multiple rows

### 5.2 Touch Target
Button height (`padding: 0.75rem`) provides adequate touch target size (~44px minimum recommended).

### 5.3 New Tab Behavior
On mobile, `window.open()` typically opens in a new browser tab or switches to a new in-app browser view. This is the expected UX for "download/view full size" actions.

## 6. Testing

### 6.1 Manual Test Cases

| Test | Steps | Expected |
|------|-------|----------|
| Button hidden initially | Load page | Button not visible |
| Button appears on image load | Click "Next" | Button becomes visible |
| Button opens full URL | Click "Full Size" | New tab opens with full-resolution image |
| Button hidden on error | Force image load error | Button hidden |
| Button hidden on next load | Click "Next" when already loaded | Button hidden during load, shown after |
| Mobile layout | View on 320px width | No horizontal scrolling |

### 6.2 Browser Compatibility
Test in:
- Chrome (desktop & mobile)
- Safari (desktop & iOS)
- Firefox (desktop)

## 7. Rollback

If issues arise:
1. Remove `<button id="btn-fullsize">` from HTML
2. Remove `handleFullSize()` function
3. Remove `btnFullSize` references from `showImage()` and `showImagePlaceholder()`
4. Remove event listener wire-up from `initLayout()`
5. Optionally keep `web_ui_text.en.yaml` addition (harmless)

The thumbnail display (Story 01) continues to work; users can still access full images via the existing `temp_url` in the API response if needed.

