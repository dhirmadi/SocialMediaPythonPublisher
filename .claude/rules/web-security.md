---
description: "FastAPI web UI security, admin auth, cookie TTL, and responsive design rules"
paths:
  - "publisher_v2/src/publisher_v2/web/**"
---

# Web UI & admin security (do not regress)

- `publisher_v2.web.app` hosts the FastAPI app; keep routes thin, delegate to services/orchestrator.
- UI is a single-page template: `publisher_v2/src/publisher_v2/web/templates/index.html` (vanilla JS + CSS, no build toolchain).
- Admin-only controls (analyze, publish, status panels) must **not be visible** to non-admin users — hide entirely, don't disable.
- Admin mode requires **both**: HTTP auth (`WEB_AUTH_TOKEN` Bearer or `WEB_AUTH_USER`/`WEB_AUTH_PASS` Basic) **and** active admin cookie (`pv2_admin`) via `publisher_v2.web.auth`.
- Admin cookie TTL: server-enforced via `WEB_ADMIN_COOKIE_TTL_SECONDS` (clamped 60–3600s).
- Admin cookie is **bound to tenant and host** (SEC-1): the signed payload carries `{sid, tenant, host, mode, email?}`. Verification compares `tenant`/`host` against `request.state.tenant`/`request.state.host` (orchestrator mode) or the normalized `Host` header (standalone) on every request; any mismatch — including legacy cookies without the claims — is not admin. Never remove this binding or accept a cookie minted for another tenant/host.
- Per-tenant auth policy: in orchestrator mode `require_admin` reads `request.state.config`; a tenant whose runtime config has Auth0 disabled (`auth0 is None`) and no password login gets 403 even with a validly signed cookie.
- Server is source of truth: `/api/admin/status` and 401/403 must clear admin state client-side.
- Mobile-first: no horizontal scrolling on 320–768px widths.
- Preserve dark-red admin theme; keep contrast accessible.
- Preserve endpoint contracts documented in `docs_v2/03_Architecture/ARCHITECTURE.md`.
