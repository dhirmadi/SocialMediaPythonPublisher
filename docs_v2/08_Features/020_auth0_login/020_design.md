# Auth0 Login Migration — Feature Design

**Feature ID:** 020
**Design Version:** 1.1
**Date:** 2025-12-07
**Status:** Implementation Complete
**Author:** AI Agent
**Feature Request:** 020_feature.md

## 1. Summary
This feature introduces Auth0 OIDC login for admin authentication while maintaining backward compatibility with the existing simple password mechanism. The system supports a "dual-mode" configuration where deployments can choose between Auth0 (SSO) or the legacy password flow.

## 2. Context & Assumptions
- **Current State:** Admin mode relies on `web_admin_pw`.
- **Architectural Context:** The application is deployed in a distributed environment (Heroku/Docker).
- **Decision:** Use **Direct OIDC Integration** via `authlib` for Auth0, but preserve the legacy password path as a fallback.
  - **Reasoning:** Ensures zero-downtime migration and allows simpler deployments to stick with passwords if desired.

## 3. Requirements
### 3.1 Functional Requirements
- **FR1:** If configured with Auth0, the "Admin" button redirects to `/api/auth/login`.
- **FR2:** If configured with only a password, the "Admin" button opens a password modal (legacy flow).
- **FR3:** `GET /api/auth/callback` handles OIDC code exchange and verifies email against `ADMIN_LOGIN_EMAILS`.
- **FR4:** `POST /api/admin/login` handles password verification (legacy).
- **FR5:** Successful login (via either method) sets the `pv2_admin` cookie.
- **FR6:** Logout endpoint clears the session and cookie.

### 3.2 Non-Functional Requirements
- **Security:** `SessionMiddleware` uses a secure `SECRET_KEY`. Cookies are `HttpOnly`. `Secure` flag defaults to true in production.
- **Observability:** Structured JSON logs for all auth events.
- **Compatibility:** Legacy `POST /api/admin/logout` is deprecated but functional.

## 4. Architecture & Design

### 4.1 Frontend Logic
The frontend (`index.html`) queries `/api/config/features` on load to determine the `auth_mode`:
- `"auth0"`: Admin button is a link to `/api/auth/login`.
- `"password"`: Admin button opens the JS modal to POST to `/api/admin/login`.
- `"none"`: Admin button is hidden.

### 4.2 Backend Components
- **`AuthRouter` (`routers/auth.py`)**: Handles OIDC Login/Callback/Logout.
- **`Auth Helpers` (`web/auth.py`)**: 
  - `is_admin_configured()`: Returns true if *either* Auth0 or Password is set.
  - `get_auth_mode()`: Determines the active mode.
  - `verify_admin_password()`: Legacy check.
- **`Config`**: Loads both Auth0 env vars and legacy `web_admin_pw`.

### 4.3 Data Model
New `Auth0Config` model added to schema. Legacy password remains as an environment variable read directly by helper functions.

### 4.4 API/Contracts
- **`GET /api/auth/login`**: Redirects to Auth0.
- **`GET /api/auth/callback`**: OIDC Callback.
- **`POST /api/admin/login`**: Legacy password login (JSON body `{"password": "..."}`).
- **`GET /api/auth/logout`**: Unified logout.

## 5. Security, Privacy, Compliance
- **Session Secret:** Required for OIDC state management. Fails fast in production if missing.
- **Cookie Security:** `pv2_admin` cookie respects `WEB_SECURE_COOKIES` setting (defaults to True).
- **Audit:** Email address is logged on login success/failure.

## 6. Rollout & Ops
- **New Deployments:** Set `AUTH0_*` vars to enable SSO.
- **Existing Deployments:** Can remain on password auth (no config change needed) or migrate by adding Auth0 vars.
- **Hybrid:** If both are set, Auth0 takes precedence in the UI, but the password endpoint remains technically accessible (though hidden).

## 7. Testing Strategy
- **`test_auth0.py`**: Covers OIDC flow (Redirect, Callback, Email Allowlist).
- **`test_auth_legacy.py`**: Covers Password flow (Login success/fail, cleanup).
