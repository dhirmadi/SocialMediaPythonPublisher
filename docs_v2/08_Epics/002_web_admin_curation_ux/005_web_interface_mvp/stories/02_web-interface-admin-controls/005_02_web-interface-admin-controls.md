# Web Interface Admin Controls

**Feature ID:** 005  
**Change ID:** 005-001  
**Status:** Shipped  
**Date Completed:** 2025-11-19  
**Code Branch / PR:** TODO  

## Summary
This change adds a lightweight admin-only mode to the Web Interface MVP so that only an administrator can trigger **Analyze & caption** and **Publish** and view detailed status/results, while captions remain visible to all users. Admin mode is unlocked via a shared password from `.env` (`web_admin_pw`) and tracked with a short-lived cookie (<1 hour), and the administrator can explicitly log out to clear admin privileges. The implementation reuses existing FastAPI/web components and HTTP auth, without altering CLI workflows or introducing new data stores.

## Goals
- Ensure that only the administrator can trigger **Analyze & caption** and **Publish** actions from the web UI.
- Ensure that only the administrator can see detailed status and per-platform publish results.
- Keep captions visible to all users while gating powerful actions and operational details behind admin mode.
- Use a simple `.env`-configured admin password (`web_admin_pw`) with a short-lived cookie to manage admin sessions.
- Preserve the existing Web Interface MVP architecture, endpoints, and CLI behavior.

## Non-Goals
- Implement a full user management or multi-role access control system.
- Replace or weaken existing HTTP-level authentication (`WEB_AUTH_TOKEN`, basic auth).
- Introduce any new persistent database or storage beyond Dropbox and sidecar files.
- Change or deprecate CLI workflows.

## User Value
This change makes the web UI safer to expose on shared or less-controlled devices by preventing casual users from triggering AI analysis or publishing, and by hiding internal operational details. The single operator can still run the full workflow from their phone or browser with minimal friction, while viewers can safely see images and captions without being able to cause side effects.

## Technical Overview
- **Scope of the change:**  
  - Web interface only: FastAPI app, web auth, web models, HTML template, and web docs.  
  - No changes to core orchestrator, AI, storage, or CLI entrypoints.
- **Core flow delta (before vs after):**
  - Before: Any web client that passed HTTP auth (if configured) could hit analyze/publish endpoints and see detailed status/results.
  - After: Web clients must (a) satisfy existing HTTP auth (if enabled) and (b) be in admin mode (cookie set) to analyze/publish and see detailed details; captions remain visible to all, and the administrator can exit admin mode to return to a viewer-only state.
- **Key components touched:**
  - `publisher_v2.config.schema.WebConfig`: extended with an `admin_cookie_ttl_seconds` field and now instantiated in `ApplicationConfig` via the loader.
  - `publisher_v2.config.loader.load_application_config`: now constructs a typed `WebConfig` and includes it in `ApplicationConfig` (behavior otherwise unchanged).
  - `publisher_v2.web.auth`:
    - Existing `require_auth` kept as-is for HTTP bearer/basic auth.
    - New admin helpers: `ADMIN_COOKIE_NAME`, `get_admin_password()`, `is_admin_configured()`, `verify_admin_password()`, `_admin_cookie_ttl_seconds()`, `set_admin_cookie()`, `clear_admin_cookie()`, `is_admin_request()`, `require_admin()`.
  - `publisher_v2.web.models`:
    - New models: `AdminLoginRequest`, `AdminStatusResponse`.
  - `publisher_v2.web.app`:
    - New endpoints:
      - `POST /api/admin/login` → verifies password from `web_admin_pw`, sets admin cookie, returns `AdminStatusResponse`.
      - `GET /api/admin/status` → returns `AdminStatusResponse` based on admin cookie.
      - `POST /api/admin/logout` → clears the admin cookie and returns `AdminStatusResponse(admin=False)`.
    - Existing endpoints:
      - `POST /api/images/{filename}/analyze` and `POST /api/images/{filename}/publish` now call `require_admin()` when admin mode is configured, in addition to `require_auth()`.
  - `publisher_v2/web/templates/index.html`:
    - Added an **Administration** button, admin login form, admin-mode indicator, admin message area, and a logout control for exiting admin mode.
    - Introduced client-side `isAdmin` state and calls to `/api/admin/status` and `/api/admin/login`.
    - Analyze/Publish buttons and the status/details panel now respect `isAdmin` (captions remain visible to all).
- **Flags / config:**
  - `.env`:
    - `web_admin_pw` — admin password required to enable admin mode.
    - `WEB_ADMIN_COOKIE_TTL_SECONDS` — optional override for admin cookie TTL (default ~1 hour).
  - Web config model: `WebConfig` is now instantiated but admin behavior is still primarily driven by env vars.
- **Data/state/sidecar updates:**
  - No new persistent data structures.
  - Admin state is held in a short-lived HTTP cookie and client-side UI state; sidecar behavior is unchanged.

## Implementation Details
- **Key functions/classes added or modified:**
  - `WebConfig` in `config/schema.py` extended with `admin_cookie_ttl_seconds`; `ApplicationConfig` now receives a `web` instance from the loader.
  - `load_application_config` now constructs `WebConfig()` and passes it into `ApplicationConfig` without changing other config semantics.
  - `web/auth.py`:
    - `get_admin_password()` reads `web_admin_pw` from the environment.
    - `verify_admin_password()` uses `hmac.compare_digest` for constant-time-ish password comparison.
    - `set_admin_cookie()` sets the `pv2_admin` cookie with configurable TTL and sane defaults for testing vs production.
    - `is_admin_request()` inspects the admin cookie; `require_admin()` enforces admin mode when configured, returning `503` if unconfigured and `403` if not in admin mode.
  - `web/models.py`:
    - `AdminLoginRequest(password: str)` and `AdminStatusResponse(admin: bool, error: Optional[str])`.
  - `web/app.py`:
    - `api_admin_login()` implements the login flow with structured logging (`web_admin_login_success` / `web_admin_login_failure` / `web_admin_login_unconfigured`).
    - `api_admin_status()` returns admin state from `is_admin_request()`.
    - `api_analyze_image()` and `api_publish_image()` now call `require_admin()` when `is_admin_configured()` is true, ensuring server-side enforcement.
  - `index.html`:
    - Admin login UI, admin-mode indicator, and UX wiring (`refreshAdminStatus()`, `handleAdminLogin()`, and `updateAdminUI()`).
    - Analyze/Publish guarded on the client (`isAdmin` check) while server endpoints also enforce admin mode.
- **Error handling:**
  - Missing `web_admin_pw` → `POST /api/admin/login` returns `503` with a generic “Admin mode not configured” message; UI surfaces a clear message and keeps admin-only features disabled.
  - Incorrect admin password → `401` with “Invalid admin password”; cookie not set.
  - Missing/expired cookie → `require_admin()` raises `403` for analyze/publish; UI messages (“Admin mode required...”) prompt re-login.
  - Admin logout → cookie is cleared, admin status becomes false, and the UI disables admin-only controls and hides admin-only details.
- **Performance / reliability:**
  - Admin login is a single password check and cookie set, negligible latency relative to existing endpoints.
  - Admin checks are pure in-memory operations (env + cookie), with no new I/O or external calls.
- **Security / privacy:**
  - `web_admin_pw` is never logged or returned in responses; only success/failure events are logged.
  - Admin cookie is `HttpOnly` and `SameSite=Lax`, with TTL capped around one hour; default `secure` is disabled for local/testing and can be enabled via env for production.
  - Admin mode is an additional guard layered on top of existing HTTP auth, not a replacement.

## Testing
- **Unit tests:**
  - `publisher_v2/tests/web/test_web_auth_admin.py`:
    - Validates `verify_admin_password()` match/mismatch behavior.
    - Verifies `require_admin()` rejects when admin is configured but no cookie is present, and accepts when cookie is set.
  - Existing `test_web_auth.py` continues to cover HTTP bearer/basic auth.
- **Integration tests:**
  - `publisher_v2/tests/web_integration/test_web_admin_endpoints.py`:
    - `test_admin_login_success` / `test_admin_login_failure` exercise `/api/admin/login`.
    - `test_admin_status_and_cookie_flow` verifies `/api/admin/status` before and after login.
    - `test_analyze_publish_require_admin` ensures analyze/publish require admin mode (403/404 without admin cookie).
  - Existing web integration tests (`test_web_endpoints.py`, `test_web_auth_integration.py`) still pass, confirming backward compatibility.
- **E2E / manual checks (per design, not automated in this change):**
  - Existing e2e web MVP test remains green; admin mode E2E can be exercised via staging Heroku deployment using `web_admin_pw`.

## Rollout Notes
- **Feature/change flags:**
  - Conceptual flag: `features.web_interface_mvp_admin_mode` (reflects that this story is an additive hardening of the web MVP).
- **Monitoring / logs:**
  - New structured events:
    - `web_admin_login_success`
    - `web_admin_login_failure`
    - `web_admin_login_unconfigured`
    - Existing `web_analyze_complete` / `web_publish_complete` continue to record admin-triggered actions.
- **Backout strategy:**
  - Disable admin mode by unsetting `web_admin_pw`, reverting to current behavior where admin gating is not enforced (still protected by HTTP auth).
  - If needed, revert the admin endpoints and template changes while leaving the underlying web MVP intact.

## Artifacts
- Change Request: docs_v2/08_Epics/08_04_ChangeRequests/005/001_web-interface-admin-controls.md  
- Change Design: docs_v2/08_Epics/08_04_ChangeRequests/005/001_web-interface-admin-controls_design.md  
- Change Plan: docs_v2/08_Epics/08_04_ChangeRequests/005/001_web-interface-admin-controls_plan.yaml  
- Parent Feature Design: docs_v2/08_Epics/08_02_Feature_Design/005_web-interface-mvp_design.md  
- PR: TODO  

## Final Notes
This story provides a pragmatic, low-complexity safety layer for the Web Interface MVP without changing its core behavior or data model. Future follow-ups could add an explicit “log out of admin mode” control, refine which status fields are considered sensitive, and make cookie TTL/configuration more visible in operator-facing documentation.
