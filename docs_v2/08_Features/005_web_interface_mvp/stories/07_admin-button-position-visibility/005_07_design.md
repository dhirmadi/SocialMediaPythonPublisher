<!-- 08_04_ChangeRequests/005/006_design.md -->

# Admin Button Position and Visibility — Change Design

**Feature ID:** 005  
**Change ID:** 005-006  
**Parent Feature:** Web Interface MVP  
**Design Version:** 1.0  
**Date:** 2025-01-27  
**Status:** Design Review  
**Author:** Evert  
**Linked Change Request:** docs_v2/08_Features/08_04_ChangeRequests/005/006_admin-button-position-visibility.md  
**Parent Feature Design:** docs_v2/08_Features/08_02_Feature_Design/005_web-interface-mvp_design.md

## 1. Summary

- **Problem & context:** The admin login button is currently positioned in the left side of the header alongside the title, which is inconsistent with common UI patterns where authentication controls are typically placed in the top right. Additionally, both the admin button and logout button can be visible simultaneously, creating visual clutter and confusion about the current authentication state.
- **Change:** Move the admin button from `header-left` to `header-right` (top right position), and update visibility logic so that the admin button is only shown when the user is not logged in, while the logout button is shown when the user is logged in, replacing the admin button in the same position.
- **Goals:** Improve UI consistency and clarity by positioning authentication controls in the standard top-right location and ensuring only one authentication button is visible at a time based on login state.
- **Non-goals:** No changes to authentication mechanism, session management, modal behavior, or other header elements.

## 2. Context & Assumptions

- **Current behavior (affected parts):**
  - The admin button (`btn-admin`) is currently in the `header-left` div alongside the title.
  - The logout button (`btn-admin-logout`) is in the `header-right` div and is hidden by default with the `hidden` class.
  - The `updateAdminUI()` function controls visibility of admin-only elements but does not hide the admin button when logged in.
  - Both buttons can potentially be visible at the same time, which is confusing.
- **Constraints inherited from parent feature:**
  - Python 3.9–3.12, FastAPI + uvicorn, single Heroku dyno.
  - Mobile-first responsive design must be maintained.
  - No changes to backend authentication or session management.
  - Existing admin modal and logout functionality must remain unchanged.
- **New assumptions for this change:**
  - Moving the admin button to `header-right` will not break the existing flexbox layout.
  - The header layout can accommodate both buttons in the same position without overflow issues.
  - The visibility toggle logic can be cleanly integrated into the existing `updateAdminUI()` function.

## 3. Requirements

### 3.1 Functional Requirements

- **CR1: Admin button positioning**
  - The admin button must be positioned in the `header-right` div (top right corner).
  - The admin button must be removed from the `header-left` div.
- **CR2: Admin button visibility**
  - The admin button must be visible only when `isAdmin === false`.
  - The admin button must be hidden when `isAdmin === true`.
- **CR3: Logout button visibility**
  - The logout button must remain visible only when `isAdmin === true`.
  - The logout button must remain hidden when `isAdmin === false`.
- **CR4: Layout preservation**
  - The header layout must remain responsive and functional on mobile devices.
  - No horizontal scrolling should be introduced by this change.
  - The title and other header elements must remain properly positioned.

### 3.2 Non-Functional Requirements

- **UX:**
  - The authentication state must be immediately clear from which button is visible.
  - Button positioning must follow common UI patterns (auth controls in top right).
- **Performance:**
  - No additional DOM manipulation or performance overhead beyond existing visibility toggles.
- **Accessibility:**
  - Button labels and ARIA attributes must remain unchanged.
  - Focus management must remain correct when buttons are shown/hidden.

## 4. Architecture & Design (Delta)

### 4.1 Current vs. Proposed

- **Current:**
  - Admin button in `header-left` div, always visible.
  - Logout button in `header-right` div, hidden/shown based on admin state.
  - `updateAdminUI()` does not control admin button visibility.
- **Proposed:**
  - Admin button moved to `header-right` div.
  - Admin button visibility controlled by `updateAdminUI()` based on `isAdmin` state.
  - Logout button remains in `header-right` div with existing visibility logic.
  - Only one button visible at a time in the top right position.

### 4.2 Components & Responsibilities

- **HTML Template (`publisher_v2/web/templates/index.html`):**
  - Move `btn-admin` button element from `header-left` to `header-right`.
  - Ensure proper DOM structure for flexbox layout.
- **JavaScript (`updateAdminUI()` function):**
  - Add logic to hide `btn-admin` when `isAdmin === true`.
  - Add logic to show `btn-admin` when `isAdmin === false`.
  - Ensure logout button visibility logic remains correct.

### 4.3 Data Flow

1. User loads page → `isAdmin` initialized to `false` → Admin button visible in top right.
2. User clicks admin button → Modal opens → User enters password → Login succeeds → `isAdmin` set to `true` → `updateAdminUI()` called → Admin button hidden, logout button shown.
3. User clicks logout → Logout succeeds → `isAdmin` set to `false` → `updateAdminUI()` called → Logout button hidden, admin button shown.

## 5. Implementation Plan

### 5.1 HTML Changes

1. Move `<button id="btn-admin">` from `header-left` div to `header-right` div.
2. Ensure the button is placed before the logout button in the DOM order.

### 5.2 JavaScript Changes

1. Update `updateAdminUI()` function:
   - Add `btnAdmin.classList.add("hidden")` when `isAdmin === true`.
   - Add `btnAdmin.classList.remove("hidden")` when `isAdmin === false`.
2. Ensure initial state: Admin button visible, logout button hidden (already handled by existing code).

### 5.3 CSS Changes

- No CSS changes required; existing `hidden` class and flexbox layout will handle visibility and positioning.

## 6. Testing Strategy

### 6.1 Manual Testing

- Verify admin button appears in top right when not logged in.
- Verify logout button appears in top right when logged in.
- Verify button visibility toggles correctly on login.
- Verify button visibility toggles correctly on logout.
- Verify layout remains responsive on mobile devices (320px–768px viewport).
- Verify no horizontal scrolling introduced.

### 6.2 Browser Testing

- Test on Chrome, Firefox, Safari (desktop and mobile).
- Verify flexbox layout works correctly across browsers.

## 7. Risks & Mitigations

- **Risk:** Button visibility logic might conflict with existing admin state management.
  - **Mitigation:** Carefully review `updateAdminUI()` to ensure both buttons are properly toggled and no race conditions exist.
- **Risk:** Layout changes might break mobile responsiveness.
  - **Mitigation:** Test on mobile viewports and ensure header flexbox layout accommodates the change without overflow.
- **Risk:** Moving button might affect focus management or accessibility.
  - **Mitigation:** Ensure button order in DOM is logical and ARIA attributes remain correct.

## 8. Rollback Plan

If issues arise:
1. Revert HTML change: Move admin button back to `header-left`.
2. Revert JavaScript change: Remove admin button visibility logic from `updateAdminUI()`.
3. No database or backend changes, so rollback is straightforward.

## 9. Success Criteria

- Admin button is positioned in top right corner.
- Admin button is only visible when user is not logged in.
- Logout button is only visible when user is logged in.
- Both buttons occupy the same position (top right) and never appear simultaneously.
- Layout remains responsive on mobile devices.
- No regressions in existing admin login/logout functionality.

