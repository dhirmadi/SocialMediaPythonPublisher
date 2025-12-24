# Horizontal Scroll Fix — Story Design

**Feature ID:** 019
**Story ID:** 019-08
**Parent Feature:** swipe_workflow_modes
**Design Version:** 1.0
**Date:** 2025-12-06
**Status:** Design Review
**Story Definition:** 019_08_horizontal_scroll_fix.md
**Parent Feature Design:** ../../019_design.md

## 1. Summary
Fix layout CSS to prevent horizontal scrolling, ensuring swipe gestures are interpreted correctly by the app logic rather than the browser moving the page.

## 2. Root Cause Analysis
- **Box Sizing:** `width: 100%` + `padding` on `main` causes overflow without `box-sizing: border-box`.
- **Preformatted Text:** The `<pre>` tag for metadata defaults to `white-space: pre`, which forces width expansion for long JSON lines.
- **Header/Main:** Flex containers might not be shrinking correctly on small screens.

## 3. Solution
### 3.1 CSS Updates
```css
/* Reset box model */
*, *::before, *::after {
  box-sizing: border-box;
}

body {
  /* Prevent horizontal scroll */
  overflow-x: hidden;
  width: 100%;
}

pre {
  /* Force wrapping for JSON data */
  white-space: pre-wrap;
  word-wrap: break-word;
  overflow-x: auto; /* Fallback scroll if needed, but perfer wrap */
  max-width: 100%;
}

img {
  max-width: 100%; /* Ensure images never overflow */
}
```

## 4. Risks
- `overflow-x: hidden` might hide content if layout is actually broken.
- `pre-wrap` might make JSON look taller. (Acceptable).

## 5. Work Plan
- Task 1: Apply CSS fixes in `index.html`.

