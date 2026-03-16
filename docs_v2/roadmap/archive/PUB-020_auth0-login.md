# PUB-020: Auth0 Login Migration

| Field | Value |
|-------|-------|
| **ID** | PUB-020 |
| **Category** | Web UI |
| **Priority** | INF |
| **Effort** | M |
| **Status** | Done |
| **Dependencies** | PUB-005 |

## Problem

The current admin authentication relies on a shared password (`web_admin_pw`) or basic auth credentials. This is difficult to manage, lacks auditability, and does not support individual user identity. We need a more robust solution that authenticates users via Auth0 and authorizes them based on their email address.

## Desired Outcome

Replace the existing password check with Auth0 OIDC flow. Secure "Admin Mode" behind Auth0 login. Authorize users by checking authenticated email against `ADMIN_LOGIN_EMAILS` allowlist. Maintain existing `pv2_admin` cookie for session management. Provide clear "Permission Denied" experience for unauthorized users. Use Direct OIDC Integration for security regardless of deployment topology.

## Scope

- Auth0 Universal Login redirect on "Admin Login" click
- OIDC callback handling; email verification against allowlist
- Session via `SessionMiddleware` with secure `WEB_SESSION_SECRET`
- OIDC `state` for CSRF protection
- Structured logging: `auth_login_start`, `auth_login_success`, `auth_login_denied`, `auth_logout`
- API-level `WEB_AUTH_TOKEN` / Basic Auth unchanged for CLI/script automation

## Acceptance Criteria

- AC1: Given I am not logged in, when I click "Admin Login", then I am redirected to the Auth0 Universal Login page
- AC2: Given I have an active Auth0 session (from another app), when I initiate login, then I am automatically logged in without re-entering credentials (SSO)
- AC3: Given I authenticate successfully, when my email matches `ADMIN_LOGIN_EMAILS` (ignoring whitespace), then I am redirected to `/` with the admin cookie
- AC4: Given I authenticate successfully, when my email does not match, then I am redirected to `/` with an error that triggers a "Permission Denied" message
- AC5: Given I am logged in, when the session expires, then I must re-authenticate

## Implementation Notes

- Auth0 env vars: `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `AUTH0_AUDIENCE`, `AUTH0_CALLBACK_URL`
- `authlib` + `httpx` for OIDC integration
- No access token storage; verify identity to set session cookie only
- Fallback to CLI tools (`WEB_AUTH_TOKEN`) if Auth0 is unavailable

## Related

- [Original feature doc](../../08_Epics/002_web_admin_curation_ux/020_auth0_login/020_feature.md) — full historical detail
