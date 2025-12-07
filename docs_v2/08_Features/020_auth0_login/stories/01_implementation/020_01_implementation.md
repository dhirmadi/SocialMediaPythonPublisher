# Story: Auth0 Login Core Implementation

**Feature ID:** 020
**Story ID:** 020-01
**Name:** implementation
**Status:** Proposed
**Date:** 2025-12-07
**Parent Feature:** 020_auth0_login

## Summary
Implement the Auth0 OIDC login flow for the Web UI, replacing the existing password-based admin login. This involves adding necessary dependencies (`authlib`, `httpx`), configuring Auth0 credentials using the provided env vars, implementing the login/callback endpoints, and updating the frontend to redirect to the new login route and handle error states gracefully.

## Scope
- Add `authlib` and `httpx` to `pyproject.toml`.
- Update `publisher_v2.config.schema` to include `Auth0Config` (mapping `AUTH0_DOMAIN`, `CLIENT_ID`, `CLIENT_SECRET`, `AUDIENCE`, `CALLBACK_URL`, `ADMIN_LOGIN_EMAILS`).
- Implement `publisher_v2.web.routers.auth` with `/login`, `/callback`, `/logout`.
- Integrate `SessionMiddleware` with secure secret loading (`WEB_SESSION_SECRET` or fallback).
- Update `publisher_v2.web.app` to include the new router and middleware.
- Update `publisher_v2.web.templates.index.html`:
  - Remove the password modal and existing admin login JS.
  - "Admin" button now links to `/api/auth/login`.
  - Add JS to parse `?auth_error=` query param and show a toast/notification (reusing existing status UI).
- Ensure `ADMIN_LOGIN_EMAILS` logic parses CSV robustly (strip whitespace).
- Preserve existing `WEB_AUTH_TOKEN` behavior for API clients.

## Out of Scope
- User management (handled in Auth0).
- RBAC beyond simple email allowlist.
- Proxy/Header-based authentication (using Direct OIDC for universal security).

## Acceptance Criteria
- **Given** `AUTH0_*` vars are configured,
- **When** I click "Admin",
- **Then** I am redirected to Auth0.
- **When** I log in successfully (or have an SSO session) with an allowed email,
- **Then** I am redirected to `/` and the `pv2_admin` cookie is set.
- **When** I log in with a disallowed email,
- **Then** I am redirected to `/?auth_error=access_denied` and the UI shows "Permission Denied".
- **When** I click "Logout",
- **Then** my session is cleared and I am redirected to `/`.

## Technical Notes
- Use `authlib.integrations.starlette_client.OAuth`.
- `SessionMiddleware` key MUST fail in production if not set.
- Use `log_json` for all auth events (audit trail).
- Validate `ADMIN_LOGIN_EMAILS` allows spaces around commas (e.g., "a@b.com, c@d.com").

## Dependencies
- `authlib`
- `httpx`

