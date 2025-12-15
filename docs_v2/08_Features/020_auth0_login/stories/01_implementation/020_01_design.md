# Auth0 Login Core Implementation — Story Design

**Feature ID:** 020
**Story ID:** 020-01
**Story Name:** auth0-core-implementation
**Parent Feature:** auth0_login
**Design Version:** 1.0
**Date:** 2025-12-07
**Status:** Implementation Complete
**Story Definition:** 020_01_implementation.md
**Parent Feature Design:** ../../020_design.md

## 1. Summary
This story implements the core Auth0 OIDC login flow for the Web UI. It replaces the password-based admin login with a secure OIDC redirects to Auth0, leveraging SSO where possible. It adds `authlib` and `httpx` dependencies, updates configuration schemas, implements the `AuthRouter`, integrates `SessionMiddleware` for OIDC state, and updates the `index.html` UI to handle the new flow and error states.

## 2. Context & Assumptions
- **Current Behavior:** Users click "Admin" -> Modal asks for password -> POST `/api/admin/login` -> Cookie set.
- **New Behavior:** Users click "Admin" -> Redirect to Auth0 -> Callback -> Check email allowlist -> Cookie set or Redirect with Error.
- **Constraints:** Must fail startup if `WEB_SESSION_SECRET` is missing in production. Must parse `ADMIN_LOGIN_EMAILS` robustly (CSV with spaces).
- **Dependencies:** `authlib`, `httpx`, `starlette.middleware.sessions`.

## 3. Requirements
### 3.1 Functional Requirements
- **SR1:** Add `authlib` and `httpx` dependencies.
- **SR2:** Implement `Auth0Config` model to validating `AUTH0_DOMAIN`, `CLIENT_ID`, `CLIENT_SECRET`, `AUDIENCE`, `CALLBACK_URL`, `ADMIN_LOGIN_EMAILS`.
- **SR3:** Add `SessionMiddleware` to `app.py` using `WEB_SESSION_SECRET`.
- **SR4:** Implement `GET /auth/login` to redirect to Auth0.
- **SR5:** Implement `GET /auth/callback` to exchange code, verify email, and set `pv2_admin` cookie on success.
- **SR6:** Implement `GET /auth/logout` to clear cookie.
- **SR7:** Update `index.html` to remove password modal and handle `?auth_error=` query params via toast/alert.

### 3.2 Non-Functional Requirements
- **Security:** Secure Session Secret handling. `pv2_admin` cookie remains HttpOnly/Secure.
- **Observability:** Structured JSON logging for all auth events (`auth_login_redirect`, `auth_callback_success`, `auth_callback_denied`, `auth_logout`).

## 4. Architecture & Design (Delta)
### 4.1 Current vs. Proposed
- **Current:** `app.py` has `/api/admin/login` (POST). Frontend has password modal JS.
- **Proposed:**
  - `app.py`: Remove `POST /api/admin/login`. Add `SessionMiddleware`. Include `auth_router`.
  - `frontend`: Remove modal HTML/JS. "Admin" button is `<a href="/auth/login">`. JS checks URL for errors on load.

### 4.2 Components & Responsibilities
- **`publisher_v2.config.schema`**: Add `Auth0Config`.
- **`publisher_v2.web.app`**: Register middleware and router.
- **`publisher_v2.web.routers.auth`**: New router for OIDC flow.
- **`publisher_v2.web.auth0`**: Helper class (optional, or keeping it simple inside router if small) to manage the OAuth client. *Decision: Keep it simple in the router or a small helper in `auth.py`.*

### 4.3 Data & Contracts
- **Config:** `AUTH0_*` env vars.
- **Session:** `request.session` used for OIDC `state`.

### 4.4 Error Handling & Edge Cases
- **Missing Secret:** `app.py` startup check -> Raise RuntimeError.
- **Auth0 Error:** Callback receives `error` param -> Redirect to `/?auth_error=<error_description>`.
- **Email Mismatch:** Callback success but email not in list -> Redirect to `/?auth_error=access_denied`.
- **State Mismatch:** `authlib` raises MismatchError -> Catch and redirect `/?auth_error=state_mismatch`.

### 4.5 Security, Privacy, Compliance
- **PII:** Only log `email` for audit. No tokens.

## 5. Detailed Flow
1. **User** clicks Admin -> `GET /auth/login`.
2. **Server** (`login`):
   - `oauth.auth0.authorize_redirect(request, redirect_uri)`.
   - Saves `state` in signed session cookie.
3. **User** authenticates at Auth0.
4. **Auth0** redirects to `CALLBACK_URL` with `code` and `state`.
5. **Server** (`callback`):
   - `oauth.auth0.authorize_access_token(request)`.
   - Verifies state (implicitly by authlib).
   - Gets `user_info` (ID token).
   - Checks `user_info['email']` against `config.auth0.admin_emails`.
   - **Success:** `set_admin_cookie(response)`, `request.session.clear()`, Redirect `/`.
   - **Fail:** `request.session.clear()`, Redirect `/?auth_error=access_denied`.

## 6. Testing Strategy
- **Unit:** Test `Auth0Config` parsing (CSVs).
  - Explicit test case: " user@example.com , other@example.com " (spaces).
- **Integration:** Test `AuthRouter` using `TestClient` and mocking `oauth.auth0`.
  - Case: Login redirect.
  - Case: Callback success (mock token exchange).
  - Case: Callback failure (email mismatch).
  - Case: Callback failure (Auth0 error).
- **E2E:** Manual verification via browser (since it involves external redirect).

## 7. Risks & Alternatives
- **Risk:** `WEB_SESSION_SECRET` rotation invalidates in-flight logins. *Acceptable.*

## 8. Work Plan
1. Add dependencies to `pyproject.toml`.
2. Update `publisher_v2.config.schema` and `publisher_v2.config.loader`.
3. Create `publisher_v2.web.routers.auth.py` with OIDC logic.
4. Update `publisher_v2.web.app.py` to add `SessionMiddleware` (fail if missing secret) and router.
5. Update `publisher_v2.web.templates.index.html` (Cleanup modal JS, simplified button).
6. Add tests in `tests/web/test_auth0.py` (Include CSV robust parsing test).
7. Verify and fix lint/types.

