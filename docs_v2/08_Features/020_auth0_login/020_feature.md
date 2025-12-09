# Auth0 Login Migration

**ID:** 020
**Name:** auth0-login
**Status:** Proposed
**Date:** 2025-12-07
**Author:** AI Agent

## Summary
Migrate the Web UI admin authentication from a simple password-based mechanism to Auth0 OIDC login. This enhances security by leveraging a managed identity provider and allows for granular access control via an allowlist of email addresses.

## Problem Statement
The current admin authentication relies on a shared password (`web_admin_pw`) or basic auth credentials. This is difficult to manage, lacks auditability, and does not support individual user identity. We need a more robust solution that authenticates users via Auth0 and authorizes them based on their email address.

## Goals
- Replace the existing `web_admin_pw` password check with an Auth0 OIDC flow.
- Secure the "Admin Mode" of the Web UI behind Auth0 login.
- Authorize users by checking their authenticated email against a configured allowlist (`ADMIN_LOGIN_EMAILS`).
- Maintain the existing `pv2_admin` cookie mechanism for session management after successful login.
- Provide a user-friendly "Permission Denied" experience for unauthorized users.
- **Architectural approach:** Use Direct OIDC Integration. This ensures security regardless of deployment topology (e.g., direct Heroku access) and leverages Auth0's SSO capabilities to "reuse" authentication sessions from the orchestrator seamlessly.

## Non-Goals
- Replacing the API-level `WEB_AUTH_TOKEN` or Basic Auth used for CLI/script automation.
- Implementing full RBAC or multi-role support beyond "Admin" vs "Guest".
- Managing users within the application database.
- Relying on upstream proxy headers for authentication (to avoid spoofing risks on public cloud PaaS).

## Users & Stakeholders
- **Primary Users:** System Administrators accessing the Web UI to curate/publish.
- **Stakeholders:** Security team, Dev team.

## User Stories
- As an **Admin**, I want to click the "Admin" button and be redirected to Auth0 to log in (SSO), so that I don't have to remember a shared password.
- As an **Admin**, I want my access to be granted only if my email is in the allowed list, so that unauthorized users cannot access admin functions.
- As an **Admin**, I want to remain logged in via a secure cookie, so I don't have to re-authenticate for every action.
- As a **Guest**, I want to see a clear "Permission Denied" message if I log in but my email is not allowed.

## Acceptance Criteria
- **Given** I am not logged in, **when** I click "Admin Login", **then** I am redirected to the Auth0 Universal Login page.
- **Given** I have an active Auth0 session (from another app), **when** I initiate login, **then** I am automatically logged in without re-entering credentials (SSO).
- **Given** I authenticate successfully, **when** my email matches `ADMIN_LOGIN_EMAILS` (ignoring whitespace), **then** I am redirected to `/` with the admin cookie.
- **Given** I authenticate successfully, **when** my email **does not** match, **then** I am redirected to `/` with an error that triggers a "Permission Denied" message.
- **Given** I am logged in, **when** the session expires, **then** I must re-authenticate.

## UX / Content Requirements
- "Admin" button triggers `GET /api/auth/login`.
- Login Callback handles the OIDC response.
- "Permission Denied" is handled via query parameter redirection (e.g., `/?error=access_denied`) shown in the existing UI (toast/modal).

## Technical Constraints & Assumptions
- **Framework:** FastAPI (`publisher_v2.web`).
- **Auth Provider:** Auth0.
- **State Management:** `SessionMiddleware` with secure secret handling.
- **Environment:** Heroku/Docker.

## Dependencies & Integrations
- **Auth0:** OIDC Provider.
- **Library:** `authlib` + `httpx` (standard, lightweight integration).

## Data Model / Schema
- **Configuration (Env Vars):**
  - `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`
  - `AUTH0_AUDIENCE`, `AUTH0_CALLBACK_URL`
  - `ADMIN_LOGIN_EMAILS` (CSV)
  - `WEB_SESSION_SECRET` (for cookie signing)

## Security / Privacy / Compliance
- Secrets loaded from env only.
- `SessionMiddleware` must use a secure key (fail in prod if missing).
- Use OIDC `state` for CSRF protection.
- Structured logging for audit trails (no PII/tokens in logs).

## Performance & SLOs
- Login redirection < 100ms.
- Token verification < 500ms.

## Observability
- Log JSON events: `auth_login_start`, `auth_login_success`, `auth_login_denied`, `auth_logout`.

## Risks & Mitigations
- **Risk:** Auth0 downtime. **Mitigation:** Admin access unavailable; fallback to CLI tools (which use `WEB_AUTH_TOKEN`).
- **Risk:** Misconfiguration of callback URL. **Mitigation:** Clear error logging and documentation.

## Open Questions
- Should we use a library like `authlib`? (Will check existing deps).
- Do we need to store the Auth0 access token? (No, we only need to verify identity to set our own session cookie).

## Milestones
- M1: Config setup and Auth0 client integration.
- M2: Login flow implementation (Redirect + Callback).
- M3: Email verification and Session handling.
- M4: UI Updates (Button + Error handling).

