<!-- docs_v2/08_Features/08_04_ChangeRequests/005/003_web-ui-admin-visibility-responsive-layout_design.md -->

# Web UI Admin Visibility & Responsive Layout — Change Design

**Feature ID:** 005  
**Change ID:** 005-003  
**Parent Feature:** Web Interface MVP  
**Design Version:** 1.0  
**Date:** 2025-11-20  
**Status:** Design Review  
**Author:** Evert  
**Linked Change Request:** docs_v2/08_Features/08_04_ChangeRequests/005/003_web-ui-admin-visibility-responsive-layout.md  
**Parent Feature Design:** docs_v2/08_Features/08_02_Feature_Design/005_web-interface-mvp_design.md  

## 1. Summary

- **Problem & context:** The current Web Interface MVP shows admin-oriented sections and actions (analysis, publishing, status) in ways that can confuse non-admin users (e.g., disabled controls), lacks a clear visual indication of admin mode, and is not yet fully responsive for mobile. Admin sessions are not explicitly short-lived, and the status area can become noisy instead of focusing on the current action.
- **Goals:** Make the UI responsive, render admin/status sections only when admin is authenticated, add a modal-based admin login flow, enforce a short-lived (≤1h) admin session, switch to a dark red background when in admin mode, and streamline status messaging into an "Activity" section that shows only the current/most recent action.
- **Non-goals:** No changes to underlying orchestrator/AI/storage logic, no new auth backends or data stores, no CLI behavior changes, and no multi-user RBAC beyond the existing admin/not-admin distinction.

## 2. Context & Assumptions

- **Current behavior (affected parts):**
  - `GET /` serves a single-page HTML UI (`publisher_v2.web.templates.index.html`) with image display, navigation controls, analysis/publish buttons, and a status area.
  - Admin-related controls and status/administration sections may be visible but disabled when not authenticated (per earlier admin-controls work).
  - The layout is desktop-first; responsiveness and mobile ergonomics are limited.
  - Status messages accumulate in a single area without a strict “current action” focus.
  - Admin authentication exists (via token/basic auth per parent design and change request 005-001) but session lifetime is not explicitly constrained to ≤1h.
- **Constraints inherited from parent feature:**
  - FastAPI-based web layer (`publisher_v2.web.app`) with stateless server design; no new DBs or persistent session stores.
  - Auth based on env-configured token/credentials (`WEB_AUTH_TOKEN`, `WEB_AUTH_USER`, `WEB_AUTH_PASS`); web must protect admin-only endpoints.
  - Dropbox + sidecars remain the source of truth; no change to underlying workflow or sidecar format.
  - Must remain backward-compatible with CLI (`publisher_v2.app`) and existing web API contracts.
- **Assumptions:**
  - Admin protection for web-initiated mutating actions is a **two-layer model**: (1) HTTP auth headers (`require_auth`) using `WEB_AUTH_TOKEN` or Basic auth, and (2) an admin-mode cookie (`require_admin`) driven by `web_admin_pw` and managed in `publisher_v2.web.auth`.
  - Server-side admin sessions are already short-lived and enforced via the admin cookie `max_age` (default 3600 seconds, configurable but clamped to ≤3600 via `WEB_ADMIN_COOKIE_TTL_SECONDS`); the browser enforces this expiry without extra client-side timers.
  - The frontend may still keep a lightweight `isAdmin` state for UI toggling, but it must treat server responses (`/api/admin/status`, 401/403 from admin-only endpoints) as the source of truth for whether admin mode is active or expired.
  - The existing HTML template can be updated without introducing a separate build step (keep inline CSS/JS model per MVP).
  - There is a single admin operator using the web UI; no need for multiple concurrent roles.

## 3. Requirements

### 3.1 Functional Requirements

- **CR1:** Admin and status/administration sections must only be rendered when the user is authenticated as admin; they must be completely hidden (not merely disabled) for non-admin users.
- **CR2:** The Analyze & Caption and Publish buttons must be visible and actionable only when admin is logged in; they must not appear at all for non-admin users.
- **CR3:** The admin button on the top left must trigger an admin login modal, presenting a password/token challenge and only enabling admin mode upon successful authentication.
- **CR4:** When in admin mode, the top-right administration button must clearly act as a logout control, ending the admin session and returning the UI to non-admin state.
- **CR5:** Admin sessions must be short-lived (≤1 hour since last successful authentication); after expiry, admin actions must require re-authentication and admin-only UI must be treated as logged out.
- **CR6:** The background (page or main shell) must switch to a dark red theme when admin mode is active and revert to the normal theme on logout or expiry.
- **CR7:** Status messages must be shown in a dedicated "Activity" section that displays only the current or most recent action and its state, replacing previous content when a new action begins.

### 3.2 Non-Functional Requirements

- The UI must be **responsive**, mobile-first, with no horizontal scrolling required for core actions on typical smartphone widths (≈320–768px).
- Changes must **preserve security**: no secrets in HTML/JS, headers, or logs; admin auth continues to be validated server-side.
- **Performance**: additional client-side logic (modal, state toggles) must not significantly degrade load time; keep assets small and avoid heavy JS frameworks.
- **Accessibility**: dark red admin background must retain sufficient contrast with foreground text and controls; modal must be keyboard navigable and screen-reader friendly where feasible.
  - Use a high-contrast dark red palette (e.g., `#8B0000` background with light text such as `#FFFFFF`) and verify at least WCAG AA contrast ratios for all text and controls in admin mode.
- **Observability**: web logs must remain structured via `log_json`, with additional events for login/logout and session expiry where appropriate.

## 4. Architecture & Design (Delta)

### 4.1 Current vs. Proposed

- **Current:**
  - `GET /` returns a static-ish HTML page with embedded JS that calls `/api/images/random`, `/api/images/{filename}/analyze`, and `/api/images/{filename}/publish`.
  - Admin auth is enforced at API endpoints via headers; the UI may rely on simple flags to disable admin buttons when auth is missing.
  - Status area shows multiple messages over time, and layout is not fully optimized for small screens.
- **Proposed:**
  - The same root endpoint continues to serve a single HTML page, now structured as:
    - Main image display area.
    - Public controls (e.g., Next Image).
    - Hidden/visible admin panel section (analysis, publish, admin-only info).
    - A dedicated "Activity" section.
  - Client-side JS maintains a boolean `isAdmin` state (derived from successful login and `/api/admin/status`) and conditionally renders/toggles admin panels and buttons.
  - An admin login modal is implemented in HTML/CSS/JS to collect credentials; success sets `isAdmin` (once `/api/admin/status` confirms `admin=true`) and triggers visual/admin UI changes; failure leaves UI in non-admin mode.
  - Admin session lifetime is enforced **server-side** via the admin cookie TTL (default 60 minutes, bounded between 60 and 3600 seconds); the frontend reacts to `/api/admin/status` and 401/403 responses from admin-only endpoints to detect expiry and reset its `isAdmin` state and UI.
  - When `isAdmin` is true and the server still treats the request as admin (cookie valid), a dark red theme (body background or main shell) is applied via a CSS class on the `<body>` or top-level container.
  - The Activity section is updated to always display only the current or most recent action (e.g., by overwriting content instead of appending).

### 4.2 Components & Responsibilities

- `publisher_v2.web.app`  
  - No major structural changes; continues to define FastAPI app and root route.
  - May be updated to pass additional config/flags into the template context (e.g., whether web auth is enabled, maximum admin session length in minutes).
- `publisher_v2.web.templates.index.html`  
  - Defines responsive layout using CSS (flexbox/grid) for image, controls, admin panel, and Activity section.
  - Adds the admin login modal markup and dark red admin theme styles.
  - Contains JS to:
    - Track `isAdmin` and admin session start time.
    - Toggle visibility of admin sections and buttons.
    - Handle login/logout button behavior and modal interactions.
    - Update the Activity section with the latest action/status only.
- `publisher_v2.web.auth` (or equivalent auth helper, if present)  
  - Enforces admin-only access at API endpoints as before.
  - Already implements admin-mode helpers based on an `httponly` cookie (`pv2_admin`) with a bounded TTL (default 3600 seconds, configurable via `WEB_ADMIN_COOKIE_TTL_SECONDS` and clamped between 60 and 3600 seconds); no new token formats (JWT, etc.) are required for this change.
  - Remains the single source of truth for admin status; the frontend must treat `/api/admin/status` and admin-protected endpoint responses as authoritative and only use client-side flags (`isAdmin`) as a UX cache.
- `publisher_v2.utils.logging`  
  - No changes to interface; may log new events such as `web_admin_login`, `web_admin_logout`, and `web_admin_session_expired`.

### 4.3 Auth Layering (Clarified)

- **HTTP auth for mutating endpoints (`require_auth`):**
  - Uses `WEB_AUTH_TOKEN` (Bearer) or `WEB_AUTH_USER`/`WEB_AUTH_PASS` (Basic) to ensure only authenticated callers can hit mutating APIs such as analyze/publish.
  - Applies to all mutating endpoints regardless of whether they are called from the web UI or another client.
- **Admin mode for web UI (`require_admin` + admin cookie):**
  - Uses `web_admin_pw` and the `pv2_admin` cookie, configured and enforced by `publisher_v2.web.auth`, to gate *web-triggered* mutating actions behind an explicit admin login step.
  - Only when both layers succeed (HTTP auth and admin cookie) are analyze/publish operations allowed from the web UI.
  - The admin login flow must never bypass or weaken `require_auth`; it is an additional guard on top of existing HTTP auth, not a replacement.
- **Frontend behavior:**
  - The admin login modal talks to `/api/admin/login`, which on success sets the admin cookie.
  - The UI calls `/api/admin/status` to discover whether the current browser session is in admin mode and to update `isAdmin` and visual state.
  - On 401/403 responses from admin-only endpoints, the UI must reset its admin state, hide admin sections, and prompt for login again.

### 4.3 Data & Contracts

- **HTTP APIs:**  
  - No breaking changes to existing endpoints:
    - `GET /api/images/random`
    - `POST /api/images/{filename}/analyze`
    - `POST /api/images/{filename}/publish`
    - `GET /health`
  - Authentication remains header-based (Bearer token or Basic Auth) per parent design.
 - **Template context:**  
 - Root route may pass:
  - `web_auth_enabled: bool` — whether HTTP auth is configured for mutating endpoints, used only for minor UX hints.
  - `admin_mode_available: bool` — derived from `is_admin_configured()`; when `false`, the admin button and admin-only sections must not be rendered at all.
  - `admin_session_max_minutes: int` — derived from the admin cookie TTL (e.g., `_admin_cookie_ttl_seconds() // 60`, typically 60). This value is **informational only** for the UI (e.g., helper text), not an enforcement mechanism.
 - **Client state:**
  - `isAdmin: boolean` — set to `true` on successful login; cleared on logout or timeout.
  - `adminLoginTimestamp?: number` — optional, used only for UX (e.g., messaging such as "last authenticated X minutes ago"); expiry is **authoritatively enforced** by the server via the admin cookie TTL and surfaced to the client via `/api/admin/status` and `401/403` responses, not by local time calculations.
 - **Sidecars / state / config:**
  - No changes to sidecar file format or storage.
  - Admin session lifetime is already enforced server-side via the admin cookie TTL (`WEB_ADMIN_COOKIE_TTL_SECONDS`, clamped between 60 and 3600 seconds); the UI must treat this as the single source of truth for expiry.

### 4.4 Error Handling & Edge Cases

- **Admin login failure:**  
  - Wrong password/token → modal shows a non-specific error message ("Authentication failed") and does not set `isAdmin`; no admin sections are displayed.
- **Session expiry:**  
  - The server enforces expiry via the admin cookie TTL (default 60 minutes, bounded via `WEB_ADMIN_COOKIE_TTL_SECONDS`).
  - On any admin action (e.g., Analyze, Publish, or an explicit `/api/admin/status` check), if the server indicates that admin mode has ended (e.g., `401/403` from an admin-only endpoint or `/api/admin/status` returns `admin=false`):
    - Client: `isAdmin` is cleared, admin sections are hidden, dark red theme is removed.
    - Activity is updated to "Admin session expired, please log in again."
    - The admin login modal is required again for further admin actions.
- **Network/API errors (analyze/publish):**
  - Activity section displays "Analyze failed: <short reason>" or "Publish failed: <short reason>" and overwrites any previous activity text.
- **No current action:**
  - Activity section may show a neutral message (e.g., "No current activity") or be empty; behavior should be consistent.
  - Because only the most recent action is shown, individual Activity messages must be self-contained and clearly indicate which operation they refer to (e.g., "Publish failed after successful analysis: …") so that users are not confused by lack of history.

### 4.5 Security, Privacy, Compliance

- Admin credentials are never hard-coded in HTML/JS; the modal only collects them and sends them to an appropriate auth endpoint or uses them to construct correct headers.
- Admin auth remains validated server-side via existing mechanisms; the client-side `isAdmin` flag and 1h timer are convenience/UX features, not the sole source of truth.
- Dark red admin theme is purely visual and must not leak any sensitive state in logs or external calls.
- Logs must not contain raw passwords/tokens; only high-level events are logged (`web_admin_login`, `web_admin_logout`, `web_admin_session_expired`) without secrets.

## 5. Detailed Flow

### Main Success Path: Admin Login and Use

1. User opens `/` on desktop or mobile.
2. Frontend initializes `isAdmin = false`, non-admin theme, admin sections hidden, Activity shows "No current activity" (or similar).
3. User taps the admin button in the top-left.
4. Admin login modal appears, prompting for credentials (e.g., password/token).
5. User submits credentials:
   - Frontend sends auth request (or sets headers) to validate admin access.
   - On success:
     - `isAdmin = true`.
     - `adminLoginTimestamp = now`.
     - Dark red admin theme class is applied to the root container/body.
     - Admin and status/administration sections become visible.
     - Top-right button text/icon changes to "Logout".
6. Admin clicks "Analyze & Caption":
   - Activity section set to "Analyzing…".
   - Frontend sends authorized POST `/api/images/{filename}/analyze`.
   - On success, Activity updates to "Analysis complete" (with optional brief details).
7. Admin clicks "Publish":
   - Activity set to "Publishing…".
   - Frontend sends authorized POST `/api/images/{filename}/publish`.
   - On success, Activity updates to "Publish complete" with result summary.
8. Admin clicks "Logout":
   - `isAdmin` cleared, admin sections hidden, top-right button reverts (or disappears), background theme returns to normal, Activity optionally updated ("Logged out").

### Edge Case: Session Expiry

1. Admin logs in at time T0.
2. Admin does not log out, and T1 ≥ T0 + 60 minutes.
3. On next admin action (e.g., click Analyze, Publish, or on a periodic check):
   - Frontend detects expiry (T1 - `adminLoginTimestamp` ≥ 60 minutes).
   - `isAdmin` cleared; admin sections hidden; dark red theme removed.
   - Activity updated to "Admin session expired, please log in again."
   - If a request is already in flight, a server 401/403 is handled similarly by resetting admin state and prompting for login.
4. Admin re-opens admin modal and logs in again to continue.

## 6. Testing Strategy (for this Change)

- **Unit Tests (JS/UI logic where feasible):**
  - Verify that `isAdmin` and `adminLoginTimestamp` changes toggle visibility of admin sections, buttons, and theme class.
  - Simulate session expiry (time delta ≥ 60 minutes) and ensure UI resets admin state and prompts login.
  - Ensure Activity section overwrites previous content when a new action begins.
- **Integration Tests (Python/FastAPI):**
  - Existing endpoint tests remain valid; optionally:
    - Confirm that admin-only endpoints still enforce auth (401/403 when no/invalid token) and that responses remain unchanged.
  - If any new minimal auth endpoint is introduced for login, add tests for success/failure and ensure secrets are not echoed.
- **Web UI Integration / E2E (manual or automated via browser tests):**
  - On mobile viewport:
    - Confirm no horizontal scroll and that image, controls, Activity, and admin sections stack correctly.
  - Confirm:
    - Non-admin view shows no admin/status sections or Analyze/Publish buttons.
    - Admin login modal appears and works; successful login reveals admin sections and dark red background.
    - Logout hides admin sections and restores normal background.
    - After 60+ minutes (simulated via adjusted cookie TTL or waiting for cookie expiry), any admin action that hits an admin-only endpoint results in 401/403, forces UI reset, and requires re-authentication.
    - Activity section only shows latest action and not an unbounded history.

## 7. Risks & Alternatives

- **Risk:** Confusion around how admin session lifetime is enforced.  
  - **Mitigation:** Treat the admin cookie TTL (server-side, via `WEB_ADMIN_COOKIE_TTL_SECONDS`) as the single source of truth; the UI should react to `/api/admin/status` and 401/403 responses instead of implementing its own time calculations.
- **Risk:** Dark red background may reduce readability or be visually jarring.  
  - **Mitigation:** Choose a dark red with high contrast and test with common devices; adjust saturation/brightness as needed.
- **Risk:** Responsive changes may inadvertently hide or misplace important controls on large screens.  
  - **Mitigation:** Use mobile-first but test responsively; keep desktop layout similar, just more flexible.
- **Alternatives:**
  - **Alt 1:** Keep disabled admin buttons visible to non-admins with a tooltip explaining they are admin-only.  
    - Rejected per change request, which explicitly wants them hidden.
  - **Alt 2:** Implement full server-side sessions with a store.  
    - Rejected due to no-new-DB constraint and preference for stateless design.

## 8. Work Plan (Scoped)

- Update `publisher_v2.web.templates.index.html`:
  - Introduce responsive layout (CSS) and dark red admin theme class.
  - Add admin login modal markup and Activity section dedicated container.
- Implement client-side JS logic:
  - Admin login modal open/close, credential submission, and handling success/failure.
  - `isAdmin` management; visibility toggling for admin sections and buttons; background theme application.
  - Activity section behavior to overwrite content on each new action.
- Wire login/logout controls:
  - Top-left admin button triggers modal.
  - Top-right button becomes logout in admin mode and resets state on click.
- Implement/admin session expiry behavior:
  - Ensure the UI reacts appropriately to `/api/admin/status` and 401/403 responses to detect expiry and reset admin state.
  - Optionally expose `admin_session_max_minutes` from backend config into template for informational messaging.
- Extend tests:
  - Add/update tests in web integration suite to cover admin-visible vs non-admin views, and Activity behavior.
  - Add minimal client-side/unit tests where infrastructure exists, plus manual E2E checks on mobile and desktop.
- Update documentation:
  - Briefly describe new UI behavior and admin session lifetime in relevant docs (e.g., implementation doc for feature 005).

## 9. Open Questions

- How exactly is admin authentication currently implemented on the server (pure token vs. Basic-only), and can we align token expiry to exactly 60 minutes to match the UI behavior? — **Resolved:** HTTP auth continues to use `WEB_AUTH_TOKEN` or `WEB_AUTH_USER`/`WEB_AUTH_PASS`, and admin sessions are already enforced via the `pv2_admin` cookie TTL (`WEB_ADMIN_COOKIE_TTL_SECONDS`, default 3600 seconds, clamped between 60 and 3600); the UI should treat this as authoritative and not introduce separate client-side timers for expiry.
- Should the Activity section display timestamps or only textual status for the current action? — Proposed answer: keep to textual status for MVP; consider timestamps later if needed.


