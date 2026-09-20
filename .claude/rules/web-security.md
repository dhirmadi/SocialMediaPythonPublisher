---
description: "FastAPI web UI security, admin auth, cookie TTL, and responsive design rules"
paths:
  - "publisher_v2/src/publisher_v2/web/**"
---

# Web UI & admin security (do not regress)

- `publisher_v2.web.app` hosts the FastAPI app; keep routes thin, delegate to services/orchestrator.
- UI is a single-page template: `publisher_v2/src/publisher_v2/web/templates/index.html` (vanilla JS + CSS, no build toolchain).
- Admin-only controls (analyze, publish, status panels) must **not be visible** to non-admin users — hide entirely, don't disable.
- Admin mode for **browser sessions** requires the signed, tenant/host-bound admin cookie (`pv2_admin`), which **only the Auth0 callback mints** (#137) — there is no password login, and adding one back is forbidden. Machine clients use HTTP auth (`WEB_AUTH_TOKEN` Bearer or `WEB_AUTH_USER`/`WEB_AUTH_PASS` Basic), which satisfies `require_auth` but **never** `require_admin`: since #137 analyze, publish, keep, remove and delete call `require_admin` unconditionally, so a header-only client gets 503 (no Auth0 configured) or 403 (no admin cookie). By default a valid cookie alone satisfies `require_auth` (#91 SEC-3 decision b); set `WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE=1` to additionally require header auth for cookie sessions when a header backend is configured.
- Admin cookie TTL: server-enforced via `WEB_ADMIN_COOKIE_TTL_SECONDS` (clamped 60–3600s).
- Cookie revocation (#91 SEC-10): logout revokes the presented `sid` in-process; rotating `WEB_ADMIN_COOKIE_EPOCH` invalidates every outstanding cookie fleet-wide without touching `WEB_SESSION_SECRET`.
- CSP uses a per-request `script-src` nonce (no `'unsafe-inline'` scripts); HSTS is sent whenever `WEB_SECURE_COOKIES` is on; logout is `POST /api/auth/logout` (CSRF-covered — never reintroduce a GET logout); Auth0 uses PKCE (S256).
- Filename allow-list (#91 SEC-11): every per-filename route (view/analyze/publish/thumbnail/curation) validates the name against the cached image listing + image-suffix allow-list before touching storage; non-members are 404.
- Admin cookie is **bound to tenant and host** (SEC-1): the signed payload carries `{sid, tenant, host, mode, email?}`. Verification compares `tenant`/`host` against `request.state.tenant`/`request.state.host` (orchestrator mode) or the normalized `Host` header (standalone) on every request; any mismatch — including legacy cookies without the claims — is not admin. Never remove this binding or accept a cookie minted for another tenant/host.
- Per-tenant auth policy: in orchestrator mode `require_admin` reads `request.state.config`; a tenant whose runtime config has Auth0 disabled (`auth0 is None`) gets 403 even with a validly signed cookie.
- Auth0 is the only admin login (#137): the admin cookie is minted only by the Auth0 callback with `mode="auth0"`; any other mode is rejected on mint and on verify. Never add, keep or reintroduce a password login path.
- Server is source of truth: `/api/admin/status` and 401/403 must clear admin state client-side.
- Mobile-first: no horizontal scrolling on 320–768px widths.
- Preserve dark-red admin theme; keep contrast accessible.
- Preserve endpoint contracts documented in `docs_v2/03_Architecture/ARCHITECTURE.md`.
