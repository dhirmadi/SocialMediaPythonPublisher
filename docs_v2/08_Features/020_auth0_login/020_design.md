# Auth0 Login Migration — Feature Design

**Feature ID:** 020
**Design Version:** 1.0
**Date:** 2025-12-07
**Status:** Design Review
**Author:** AI Agent
**Feature Request:** 020_feature.md

## 1. Summary
This feature replaces the shared password admin authentication with an Auth0 OIDC flow. It enhances security by identifying individual users and authorizing them based on an email allowlist configured via `ADMIN_LOGIN_EMAILS`.

## 2. Context & Assumptions
- **Current State:** Admin mode relies on `web_admin_pw`.
- **Architectural Context:** The application is deployed in a distributed environment (Heroku/Docker) where an orchestrator exists.
- **Decision:** We will implement **Direct OIDC Integration** using `authlib`.
  - **Reasoning:** This approach is robust against deployment topology changes (works on Heroku direct access, local dev, and behind proxies). It achieves "reuse" of the orchestrator's authentication via **Single Sign-On (SSO)**—users already logged into Auth0 via the orchestrator will be automatically logged into the app without re-entering credentials.
- **Dependencies:** `authlib`, `httpx`.

## 3. Requirements
### 3.1 Functional Requirements
- **FR1:** "Admin" button triggers redirect to Auth0 (`/api/auth/login`).
- **FR2:** `GET /api/auth/callback` handles the code exchange and ID token verification.
- **FR3:** Access is granted only if the ID token's `email` matches `ADMIN_LOGIN_EMAILS` (robust CSV parsing).
- **FR4:** Successful login sets the `pv2_admin` cookie and redirects to `/`.
- **FR5:** Unauthorized login (email mismatch) redirects to `/` with an error query param (e.g., `?auth_error=access_denied`).
- **FR6:** Logout endpoint clears the session.

### 3.2 Non-Functional Requirements
- **Security:** Use `SessionMiddleware` with a secure `SECRET_KEY`. Enforce OIDC `state` parameter.
- **Observability:** Use structured logging (`log_json`) for all auth events.
- **Configuration:** Support standard Auth0 env vars (`AUTH0_DOMAIN`, `CLIENT_ID`, `CLIENT_SECRET`, `AUDIENCE`, `CALLBACK_URL`).

## 4. Architecture & Design

### 4.1 Proposed Architecture
- **Frontend:** Update `index.html` to handle the `auth_error` query param and show a toast/modal. "Admin" button links to `/api/auth/login`.
- **Backend:**
  - **Auth0 Integration:** Use `authlib` Starlette integration.
  - **Router:** `publisher_v2.web.routers.auth`.
  - **Middleware:** Add `SessionMiddleware` to `app.py`.

### 4.2 Components & Responsibilities
- **`Config`**: Load Auth0 credentials and `ADMIN_LOGIN_EMAILS`. Validate emails (strip whitespace).
- **`AuthRouter`**:
  - `login()`: Initiates OIDC flow.
  - `callback()`: Processes token, checks email, sets cookie.
  - `logout()`: Clears cookie.
- **`Web UI`**: Detects login errors on load.

### 4.3 Data Model / Schemas
New Config Models in `publisher_v2.config.schema`:
```python
class Auth0Config(BaseModel):
    domain: str
    client_id: str
    client_secret: str
    audience: Optional[str] = None
    callback_url: str  # Full URL, e.g. https://app.com/api/auth/callback
    admin_emails: str  # CSV
```

### 4.4 API/Contracts
- **`GET /api/auth/login`**: Redirects to Auth0.
- **`GET /api/auth/callback`**:
  - Success: Redirect to `/` (Cookie Set).
  - Failure (Auth0 error or Email mismatch): Redirect to `/?auth_error=reason`.
- **`GET /api/auth/logout`**: Redirects to `/`.

### 4.5 Error Handling
- **Missing Session Secret:** Fail startup in production.
- **OIDC Errors:** Log structured error, redirect user to UI with error message.
- **Email Mismatch:** Log "auth_access_denied" (audit), redirect to UI with "access_denied".

### 4.6 Security, Privacy, Compliance
- **Session Secret:** Must be loaded from `WEB_SESSION_SECRET` or `SECRET_KEY`.
- **Logging:** Log `email` for audit; never log `access_token` or `client_secret`.

## 5. Detailed Flow
1. **Login:** User clicks "Admin" -> `GET /api/auth/login`.
2. **Redirect:** App redirects to Auth0 (with `state`).
3. **SSO:** If user is logged in at `org.shibari.photo`, Auth0 immediately redirects back with code.
4. **Callback:** `GET /api/auth/callback`.
5. **Exchange:** Server exchanges code for ID Token.
6. **Verify:**
   - Validate ID Token signature.
   - Extract `email`.
   - Check against `ADMIN_LOGIN_EMAILS`.
7. **Result:**
   - **Match:** Set `pv2_admin` cookie -> Redirect `/`.
   - **No Match:** Redirect `/?auth_error=access_denied`.

## 6. Rollout & Ops
- Set `AUTH0_*` and `WEB_SESSION_SECRET` env vars.
- Update `ADMIN_LOGIN_EMAILS`.
- Deploy.

## 7. Testing Strategy
- **Unit:** Mock `authlib.integrations.starlette_client.OAuth.create_client`.
- **Integration:** Test `ADMIN_LOGIN_EMAILS` parsing with spaces/commas.

## 8. Risks & Alternatives
- **Risk:** Session Secret leakage. **Mitigation:** Rotate secrets, use secure cookies.
- **Alternative:** Trusted Header Auth (from Orchestrator). **Discarded:** Requires strict network trust (no direct internet access to container). Direct OIDC is safer on public cloud (Heroku) and provides the same SSO UX.

## 9. Work Plan
- **M1:** Add dependencies (`authlib`, `httpx`).
- **M2:** Implement Config & Auth0 Service.
- **M3:** Implement Routes.
- **M4:** Update UI.

## 10. Derived Stories
- **Story 01:** Core Implementation
  - Add dependencies.
  - Add Config models.
  - Create `publisher_v2.web.auth0` helper.
  - Create `publisher_v2.web.routers.auth` router.
  - Update `app.py` to include router.
  - Update `index.html` to use new flow.
  - Update docs.

