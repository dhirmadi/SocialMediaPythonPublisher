<!-- 08_04_ChangeRequests/005/006_admin-button-position-visibility.md -->

# Admin Button Position and Visibility

**Feature ID:** 005  
**Change ID:** 005-006  
**Status:** Shipped  
**Date Completed:** 2025-01-27  
**Code Branch / PR:** admin-button

## Summary
Repositioned the admin login button from the left side of the header to the top right, and updated visibility logic so that the admin button is only shown when the user is not logged in. When the user is logged in, the logout button replaces the admin button in the same position.

## Goals
- Move the admin button from `header-left` to `header-right` (top right position).
- Show the admin button only when the user is not logged in.
- Show the logout button only when the user is logged in, replacing the admin button in the same position.
- Maintain existing functionality for both buttons (admin login modal and logout action).

## Non-Goals
- Changing the authentication mechanism or session management.
- Modifying the admin modal or logout behavior.
- Adding new authentication features or controls.
- Changing the layout of other header elements.

## User Value
Users now have a clearer, more intuitive interface where authentication controls are consistently positioned in the top right corner, and the current authentication state is immediately obvious from which button is visible.

## Technical Overview
- **Scope of the change:** HTML template and JavaScript visibility logic in `publisher_v2/web/templates/index.html`.
- **Core flow delta:** Admin button moved from `header-left` to `header-right` div, and `updateAdminUI()` function now controls admin button visibility based on `isAdmin` state.
- **Key components touched:**
  - `publisher_v2/web/templates/index.html`: moved `btn-admin` button element and updated `updateAdminUI()` function.
- **Flags / config:** No new configuration required; change is UI-only.
- **Data/state/sidecars:** No changes; authentication state management remains unchanged.

## Implementation Details
- Moved `<button id="btn-admin">` from `header-left` div to `header-right` div, positioned before the logout button.
- Updated `updateAdminUI()` JavaScript function to toggle admin button visibility:
  - When `isAdmin === true`: `btnAdmin.classList.add("hidden")` (hides admin button), `btnAdminLogout.classList.remove("hidden")` (shows logout button).
  - When `isAdmin === false`: `btnAdmin.classList.remove("hidden")` (shows admin button), `btnAdminLogout.classList.add("hidden")` (hides logout button).
- No CSS changes required; existing `hidden` class and flexbox layout handle visibility and positioning correctly.
- Button positioning works correctly on mobile viewports; no horizontal scrolling introduced.

## Testing
- **Unit tests:** No new unit tests required; existing web UI tests continue to pass.
- **Integration / E2E tests:** Existing tests (`test_web_admin_visibility.py`, `test_web_index_responsive.py`) validated that:
  - Admin sections remain properly hidden for non-admin users.
  - Responsive layout continues to work correctly.
  - JavaScript contracts remain intact.
- **Manual checks (verified):**
  - Admin button appears in top right when not logged in.
  - Logout button appears in top right when logged in.
  - Button visibility toggles correctly on login/logout.
  - Layout remains responsive on mobile devices (320px–768px viewport).

## Rollout Notes
- **Feature/change flags:** No flags required; change is immediately active.
- **Monitoring / logs:** No new logging required; existing admin login/logout events remain unchanged.
- **Backout strategy:** If issues arise, revert the HTML change (move admin button back to `header-left`) and remove admin button visibility logic from `updateAdminUI()` function.

## Artifacts
- Change Request: docs_v2/08_Epics/08_04_ChangeRequests/005/006_admin-button-position-visibility.md  
- Change Design: docs_v2/08_Epics/08_04_ChangeRequests/005/006_design.md  
- Change Plan: docs_v2/08_Epics/08_04_ChangeRequests/005/006_plan.yaml  
- Parent Feature Design: docs_v2/08_Epics/08_02_Feature_Design/005_web-interface-mvp_design.md  
- Code Changes: `publisher_v2/src/publisher_v2/web/templates/index.html`

## Final Notes
- The change improves UI consistency by following common patterns where authentication controls are positioned in the top right corner.
- The implementation is minimal and focused, reusing existing patterns (`hidden` class, `updateAdminUI()` function) without introducing new abstractions.
- No backend changes were required; the change is purely frontend and maintains full backward compatibility.
