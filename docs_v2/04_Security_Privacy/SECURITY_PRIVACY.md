# Security & Privacy — Social Media Publisher V2

Version: 2.0
Last Updated: April 25, 2026

## 1. Secrets and Sessions
- Secrets only in `.env`; never in INI; never in logs
- Redaction middleware for logs (sk-*, r8_*, bot tokens, passwords)
- Instagram sessions encrypted at rest (Fernet) where practical; always git‑ignored
- Orchestrator mode: per-tenant secrets are resolved on-demand via the orchestrator credentials endpoint and must never be persisted to disk

## 2. Filesystem Hygiene
- Temp files created 0600; deleted in finally blocks
- Optional secure overwrite for sensitive data (config flag)
- Archive/move operations performed via the configured storage backend API (Dropbox or managed storage); no long-lived local persistence

## 3. Network and API
- TLS by default; timeouts set; retries with backoff
- Rate limits per vendor; avoid bans
- No long‑term public hosting of user images for analysis (use temporary links)
- Web admin endpoints that mutate state remain protected by HTTP auth + server-enforced admin session TTL (cookie)

## 4. Privacy
- No PII stored beyond what user provides (sender/recipient email)
- Captions avoid personal data extraction by design
- Logs exclude asset content; contain only IDs and concise summaries

## 5. Compliance‑ready Practices
- Clear separation between secrets and config
- Automated checks (safety, bandit) in CI/CD (future)

## Web hardening (#91, Audit 2026-09)

- **Auth model (SEC-3, decision b):** browser admin sessions authenticate via the signed,
  tenant/host-bound `pv2_admin` cookie; machine clients via Bearer/Basic headers. A valid cookie
  alone satisfies `require_auth` by default; `WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE=1` opts into
  requiring header auth in addition to the cookie when a header backend is configured.
- **CSP & transport (SEC-8):** `script-src 'self' 'nonce-<per-request>'` (no inline-script
  allowance); `connect-src 'self' https:` (the Full Size control fetches per-tenant presigned
  storage URLs); HSTS (`max-age=31536000; includeSubDomains`) whenever `WEB_SECURE_COOKIES` is
  enabled; logout is `POST /api/auth/logout` under the CSRF middleware; the Auth0 client is
  registered with PKCE (`code_challenge_method=S256`).
- **Revocation (SEC-10):** logout revokes the presented cookie `sid` (bounded, TTL-pruned
  in-process set). `WEB_ADMIN_COOKIE_EPOCH` is a fleet-wide kill switch: rotating it invalidates
  all outstanding cookies without rotating `WEB_SESSION_SECRET`. Rate limiters refuse new keys
  with 429 at key capacity, and the library upload/delete per-cookie stores prune on every check.
- **Object-name allow-list (SEC-11):** all per-filename web operations validate the name against
  the current image listing and the image-suffix allow-list before any storage call; sidecar
  names, traversal-shaped names and unknown objects return 404.
