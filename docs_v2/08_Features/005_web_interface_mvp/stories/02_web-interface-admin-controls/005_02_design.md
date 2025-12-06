# Web Interface Admin Controls — Change Design

**Feature ID:** 005  
**Change ID:** 005-001  
**Parent Feature:** Web Interface MVP  
**Design Version:** 1.0  
**Date:** 2025-11-19  
**Status:** Design Review  
**Author:** Evert  
**Linked Change Request:** docs_v2/08_Features/08_04_ChangeRequests/005/001_web-interface-admin-controls.md  
**Parent Feature Design:** docs_v2/08_Features/08_02_Feature_Design/005_web-interface-mvp_design.md  

## 1. Summary

- **Problem & context:** The Web Interface MVP currently exposes **Analyze & caption** and **Publish** controls and detailed status information to any user who can access the UI (subject only to HTTP-level auth), which increases the risk of accidental or unauthorized actions and leaks of operational details.  
- **Change:** Introduce a lightweight **admin mode** backed by a `.env`-configured password (`web_admin_pw`) and a short-lived cookie (<1h) so that only the administrator can trigger analysis/publishing and see detailed status, while captions remain visible to all.  
- **Goals:** Preserve the existing web architecture (FastAPI app + endpoints + templates), reuse existing auth mechanisms, and keep CLI behavior unchanged, while adding a thin guard layer that aligns with the single-operator assumption.  
- **Non-goals:** No new databases, no full user management or multi-role system, no replacement for existing HTTP-level authentication.

## 2. Context & Assumptions

- **Current behavior (affected parts):**
  - The FastAPI web app (`publisher_v2.web.app`) serves a single-page UI (`index.html`) with controls for **Next image**, **Analyze & caption**, and **Publish**, plus caption and status display.
  - Any caller that passes existing HTTP-level auth (if configured) can:
    - Call `/api/images/random`, `/api/images/{filename}/analyze`, and `/api/images/{filename}/publish`.
    - Use all buttons in the UI and see status / per-platform results.
  - There is no notion of “admin mode” within the UI; the page does not differentiate viewer vs operator.
- **Constraints inherited from parent feature:**
  - Python 3.9–3.12, FastAPI + uvicorn, single Heroku dyno.
  - No new persistent databases; Dropbox + sidecars remain source of truth.
  - Authentication for the web API is via token/basic auth (optional) configured in `WebConfig`; must not be broken.
  - Web layer must remain stateless and horizontally scalable.
  - CLI behavior and configuration remain unchanged and backward compatible.
- **New assumptions for this change:**
  - A single admin password is configured in `.env` as `web_admin_pw`.
  - Admin mode can be represented as a short-lived cookie (expiry < 1 hour) indicating “admin authenticated” to the server.
  - Captions are safe to show to non-admins; only action buttons and detailed status fields are admin-only.
  - If `web_admin_pw` is missing or empty, admin mode is considered disabled and the system should behave as “viewer-only” for admin features.
- **Dependencies:**
  - Internal: `publisher_v2.web.app`, templates under `publisher_v2/web/templates`, web auth helpers (`publisher_v2.web.auth`), `config.loader` / `schema`, structured logging utilities.
  - External: Environment variables (for `web_admin_pw`), HTTP cookies in the browser, existing HTTP auth mechanisms.

## 3. Requirements

### 3.1 Functional Requirements

- **CR1: Admin login flow**
  - Provide an **Administration** control in the UI that lets the operator enter the admin password.
  - On successful password entry, the system enters **admin mode** for the browser session, tracked via a short-lived cookie (<1h).
- **CR2: Admin-only controls**
  - When **not in admin mode**, the **Analyze & caption** and **Publish** actions must not be invokable from the UI (buttons hidden or clearly disabled).
  - When **in admin mode**, these buttons must be available and behave exactly as in the existing Web Interface MVP.
- **CR3: Admin-only status visibility**
  - When **not in admin mode**, detailed status, per-platform results, and other operational details must not be shown (or must be replaced with minimal placeholders).
  - Captions (human-readable caption field) must remain visible to all users regardless of admin mode.
- **CR4: Env-driven availability**
  - If `web_admin_pw` is not defined or is empty in the environment, admin mode is disabled:
    - The UI must clearly indicate that admin-only actions are unavailable.
    - No admin login attempt should ever succeed.
- **CR5: Backend alignment**
  - The backend must enforce an admin check for actions that are meant to be admin-only at the web layer (e.g., analyze/publish endpoints when invoked from the UI), so that UI-only changes cannot bypass the guard.
  - Existing HTTP auth (Bearer/basic) remains in effect; admin mode is an additional requirement, not a replacement.
 - **CR6: Admin logout**
   - Provide a clear, explicit way for the administrator to **log out** of admin mode from the UI.
   - Logging out must delete/expire the admin cookie so that subsequent requests are treated as non-admin until the next successful login.

### 3.2 Non-Functional Requirements

- **Security:**
  - Never log or echo the admin password; sanitize logs and error messages.
  - Use an HTTP cookie with:
    - Short expiry (≤ 1 hour).
    - `HttpOnly` and `SameSite` flags where compatible, to reduce XSS and CSRF risk.
  - Avoid storing the raw password on the client; only store an opaque admin-session indicator.
- **Performance:**
  - Admin login should be O(1) and add negligible latency (<50ms typical).
  - No additional network round trips other than the login request itself and the existing API calls.
- **Observability:**
  - Log admin login attempts as structured events without secrets (e.g., `web_admin_login_success`, `web_admin_login_failure`).
  - Log usage of admin-only actions (analyze/publish) with a flag indicating admin-mode context.
- **UX/accessibility:**
  - The admin state must be visually obvious (badge/label).
  - Error and information messages must be easily understandable for non-technical operators.

## 4. Architecture & Design (Delta)

### 4.1 Current vs. Proposed

- **Current:**
  - UI shows **Next image**, **Analyze & caption**, **Publish**, caption text, and status/results to any authenticated web user.
  - Backend endpoints accept requests as long as HTTP auth passes; no additional admin concept.
  - No admin login endpoint, no admin cookie, and no gating in templates or handlers.
- **Proposed:**
  - Add a simple **admin login endpoint** that verifies a password from the client against `web_admin_pw` and, on success, issues a short-lived admin cookie.
  - Update the UI template and JS to:
    - Provide an “Administration” interaction for entering the password.
    - Read admin status (e.g., from a small API or initial render context) and conditionally render/enable admin-only controls and status.
  - Extend analyze/publish web handlers to enforce admin mode (in addition to existing HTTP auth) when calls originate via the web UI.

### 4.2 Components & Responsibilities

- `publisher_v2/web/app.py`
  - Define a new FastAPI route, e.g., `POST /api/admin/login`, to handle admin authentication.
  - Optionally define a small `GET /api/admin/status` to expose current admin-mode state to the frontend without leaking sensitive information.
  - Wire in dependency injection for `web_admin_pw` (from environment/config).
- `publisher_v2/web/auth.py`
  - Add helpers:
    - `verify_admin_password(candidate: str, actual: str) -> bool`
    - `set_admin_cookie(response, expires_in_seconds: int) -> None`
    - `require_admin(request) -> None` (raises HTTP 403 if admin cookie not present/valid).
  - Centralize cookie name, expiry, and flag configuration.
- `publisher_v2/web/templates/index.html`
  - Add UI elements:
    - “Administration” trigger.
    - Password entry form (inline or modal).
    - Admin-mode indicator (badge/label).
  - Conditionally render or disable:
    - Analyze/Publish buttons.
    - Status/result sections.
- `publisher_v2/web/service.py` (if present for web orchestration)
  - Ensure that methods used by admin-only actions assume admin checks have already passed higher up; avoid duplicating logic.

### 4.3 Data & Contracts

- **New endpoint: `POST /api/admin/login`**
  - **Request body:**
    - `{ "password": "<string>" }`
  - **Behavior:**
    - Compare `password` to `web_admin_pw` (constant-time comparison where feasible).
    - On success:
      - Set an `admin_mode` cookie with expiry <1h.
      - Return `200 OK` with `{ "admin": true }`.
    - On failure:
      - Do **not** indicate which part was wrong; return `401 Unauthorized` with `{ "admin": false, "error": "Invalid admin password" }`.
- **Optional endpoint: `GET /api/admin/status`**
  - **Response:**
    - `{ "admin": true }` if valid cookie present; `{ "admin": false }` otherwise.
- **Existing endpoints:**
  - `POST /api/images/{filename}/analyze`
  - `POST /api/images/{filename}/publish`
  - These should be updated to:
    - Apply `require_admin` middleware/dependency for web-triggered flows when `web_admin_pw` is configured.
    - Preserve existing behavior for HTTP auth and dry/preview modes.
- **Config / state changes:**
  - Read `web_admin_pw` from `.env` (e.g., via existing config loading).
  - New cookie configuration constants (name, TTL, flags) in web module; no new persistent state.
 - **New endpoint: `POST /api/admin/logout`**
   - **Behavior:**
     - Clear the admin cookie for the current client.
     - Return `200 OK` with `{ "admin": false }` to signal that admin mode is now off.

### 4.4 Error Handling & Edge Cases

- **Missing `web_admin_pw`:**
  - `POST /api/admin/login` returns `503 Service Unavailable` or `400 Bad Request` with a generic message like “Admin mode not configured”.
  - UI should surface a clear message: “Admin mode is unavailable (not configured).”
- **Incorrect password:**
  - Return `401 Unauthorized` with a generic error; never include hints about the expected password.
  - Do not set or extend the admin cookie.
- **Expired cookie:**
  - `GET /api/admin/status` returns `{ "admin": false }`.
  - `require_admin` fails with `403 Forbidden` on analyze/publish; UI should handle this by re-prompting for the password.
- **Partial failures:**
  - If cookie setting fails, treat login as unsuccessful; return an appropriate error.
  - If analyze/publish fail due to non-admin access, return `403 Forbidden` with a safe error string (no internals).

### 4.5 Security, Privacy, Compliance

- Do not log:
  - Raw passwords from requests.
  - Cookie values or decrypted admin indicators.
- Ensure cookies:
  - Use `HttpOnly` and `Secure` where the deployment platform supports HTTPS (Heroku does).
  - Use `SameSite=Lax` or `Strict` since the UI and API share the same origin.
- Respect existing content rules (PG-13, no NSFW publishing) from the parent design.
- Ensure admin mode does not override or bypass safety/preview modes; it only controls who can trigger actions, not what those actions do.

## 5. Detailed Flow

### 5.1 Admin Login Flow

1. User opens `/` and the HTML/JS loads.
2. Frontend calls `GET /api/admin/status` (optional) to determine current admin state.
3. UI renders:
   - “Administration” control.
   - Analyze/Publish buttons and status areas in disabled/hidden state if `admin=false`.
4. Operator clicks **Administration** and enters password.
5. Frontend sends `POST /api/admin/login` with `{ "password": "<entered>" }`.
6. Backend:
   - If `web_admin_pw` is not configured → return admin-unavailable error.
   - Else verify password:
     - On success: set admin cookie (<1h TTL); return `{ "admin": true }`.
     - On failure: return `{ "admin": false, "error": "Invalid admin password" }`.
7. Frontend:
   - On success: update UI to admin mode (enable buttons, show status).
   - On failure: show error message and keep admin-only features disabled.

### 5.2 Analyze & Publish in Admin Mode

1. With admin cookie set and `GET /api/admin/status` indicating `admin=true`, UI enables **Analyze & caption** and **Publish** buttons.
2. Operator clicks **Analyze & caption**:
   - Frontend calls existing `POST /api/images/{filename}/analyze`.
   - Backend applies:
     - Existing HTTP auth checks.
     - `require_admin` to ensure admin cookie is present and valid.
   - On success, backend returns analysis/caption; UI updates caption (visible to all) and admin-only status fields (visible only in admin mode).
3. Operator clicks **Publish**:
   - Similar pattern via `POST /api/images/{filename}/publish` with `require_admin`.
   - Backend runs existing orchestrator and returns per-platform results; UI shows results in admin-only section.

### 5.3 Admin Mode Expiry and Disabled State

- **Expiry:**
  - After cookie expiry (<1h), `GET /api/admin/status` returns `admin=false`.
  - If the operator attempts analyze/publish, `require_admin` returns `403`; UI must interpret this as “admin session expired” and re-prompt for password.
- **Disabled (no `web_admin_pw`):**
  - `POST /api/admin/login` always returns an error; cookie is never set.
  - UI displays a banner or inline message (e.g., “Admin mode is not configured in this deployment”) and keeps admin-only controls unavailable.
 - **Logout:**
   - When the administrator activates the “Exit admin mode” control in the UI, the frontend calls `POST /api/admin/logout`.
   - Backend clears the admin cookie and returns `{ "admin": false }`.
   - Frontend updates local `isAdmin` state to `false`, disables admin-only controls, and hides admin-only details.

## 6. Testing Strategy (for this Change)

- **Unit Tests (e.g., `publisher_v2/tests/web/test_web_auth_admin.py`):**
  - Verify `verify_admin_password` behavior (including constant-time comparison assumptions where feasible).
  - Verify cookie helper sets correct name, TTL, and flags.
  - Test `require_admin` with/without valid cookie.
- **Unit/Service Tests (e.g., `tests/web/test_web_admin_service.py`):**
  - Test `POST /api/admin/login` logic with:
    - Correct password.
    - Incorrect password.
    - Missing `web_admin_pw`.
- **Integration Tests (e.g., `publisher_v2/tests/web_integration/test_web_admin_endpoints.py`):**
  - Using FastAPI `TestClient`, test:
    - `GET /api/admin/status` for admin vs non-admin sessions.
    - Analyze/publish endpoints returning `403` without admin cookie and `200` with it.
- **UI / Template Tests (lightweight):**
  - Ensure that when `admin=false`, analyze/publish buttons are hidden or disabled and status information is not present.
  - When `admin=true`, controls are visible and functional.
- **E2E / Manual:**
  - On a staging Heroku app:
    - With `web_admin_pw` set: verify successful login, admin-only actions, and cookie expiry behavior.
    - Without `web_admin_pw`: verify admin mode is unavailable and that the UI messaging is clear.

## 7. Risks & Alternatives

- **Risk:** Admin mode is enforced only via a cookie check; if misconfigured, it may not provide strong protection.  
  **Mitigation:** Treat admin mode as an additional guard on top of existing HTTP auth and document operational expectations clearly; keep `require_admin` centralized and tested.
- **Risk:** Cookie-based admin sessions could be vulnerable to XSS if any script injection vectors exist.  
  **Mitigation:** Use `HttpOnly` cookies, preserve existing escaping/sanitization practices, and keep inline JS minimal and controlled.
- **Risk:** Operator confusion when `web_admin_pw` is missing or misconfigured.  
  **Mitigation:** Provide explicit UI messaging when admin mode is disabled and surface config expectations in documentation.
- **Alternatives considered:**
  - **Rely solely on HTTP-level auth (WEB_AUTH_TOKEN/basic):** Stronger from a protocol standpoint, but less convenient for per-device admin toggling and does not provide explicit “admin mode” concept in the UI.
  - **Implement full user accounts / sessions:** Overkill for single-operator MVP; rejected due to complexity and new persistence requirements.

## 8. Work Plan (Scoped)

- **Task 1:** Extend web configuration loading to read `web_admin_pw` from `.env` and expose it to the web layer (without logging it).  
- **Task 2:** Implement admin auth helpers in `publisher_v2/web/auth.py` (password verification, cookie management, `require_admin`).  
- **Task 3:** Add `POST /api/admin/login` (and optional `GET /api/admin/status`) to `publisher_v2/web/app.py`, wiring in logging and error handling.  
- **Task 4:** Update `publisher_v2/web/app.py` analyze/publish routes (or dependencies) to enforce `require_admin` when `web_admin_pw` is configured.  
- **Task 5:** Update `publisher_v2/web/templates/index.html` (and inline JS) to add the Administration UI, admin-mode indicator, and conditional rendering/enabling of admin-only controls and status sections.  
- **Task 6:** Add unit and integration tests as described in §6; ensure coverage of admin success, failure, expiry, and disabled modes.  
- **Task 7:** Update relevant docs (web MVP implementation doc) to mention admin mode, `web_admin_pw`, and expected behavior when admin is disabled.

## 9. Open Questions

- Should the admin cookie be renewable on activity (sliding expiry) or fixed-duration from login? — Proposed answer: fixed-duration (<1h) to keep behavior simple for MVP.  
- Should any additional sensitive fields beyond status/results (e.g., correlation IDs) be hidden from non-admins in the UI? — Proposed answer: review and hide any obviously internal identifiers, leaving only user-meaningful messages visible to non-admins.  

