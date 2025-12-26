# Epic 001 — Single Dyno Fleet, Multi‑Tenant, Domain‑Based Runtime Config (Orchestrator‑Sourced)

**ID:** 001  
**Name:** single-dyno-multi-tenant-domain-runtime-config  
**Status:** Ready for implementation (Contract locked; remaining open questions are non-blocking)  
**Date:** 2025-12-21  
**Owner:** Product / Platform  
**Last updated:** 2025-12-25

## Summary

Move from “one Heroku app/dyno per tenant” to a **single Heroku app (small dyno fleet)** that serves **hundreds of tenants** via wildcard subdomains (`xxx.shibari.photo`).  
Per-tenant behavior is determined by **platform-orchestrator**, which returns **runtime config** for a given host (`Host` header). Publisher V2 becomes a **stateless execution plane** that:

- Resolves tenant from domain
- Fetches runtime config and provider credentials from the orchestrator
- Runs the same V2 workflow (view → analyze/caption → publish → archive/curate) scoped to that tenant

This epic is the canonical plan for multi-tenant V2.

## Context (Current State)

- V2 is running on **Heroku** (FastAPI web app).
- Admin access uses **Auth0** OIDC (Feature 020).
- Today’s architecture is effectively **single-tenant per app instance**:
  - One config per deployment (INI / env vars)
  - One Dropbox account per deployment (via Dropbox OAuth refresh token)
- In dev/non-prod, provisioning has been done via separate dynos/apps (see Feature 011).

## Goals

- **Scale to a few hundred tenants** using a single Heroku application (optionally multiple web dynos).
- Route tenants by domain: `xxx.shibari.photo` → tenant `xxx`.
- Orchestrator is **source of truth** for:
  - Tenant/app identity and type
  - Feature flags / mode (review vs publish)
  - Storage provider selection and paths
  - Publisher enablement/config
  - Provider credentials (via references + a credential resolution endpoint)
- Keep V2 safety guarantees:
  - Preview-like / non-destructive behavior must remain possible.
  - Mutating operations remain strongly protected (Auth0 + admin mode).
- Enable future storage providers beyond Dropbox with minimal churn.

## Non‑Goals

- Multi-app routing within a single tenant domain (e.g., `xxx.shibari.photo/appA`).  
  **Decision:** *one app per tenant instance*; app type is determined by orchestrator.
- Building a public multi-user product with RBAC. We remain “operator/admin vs non-admin”.
- Replacing Auth0; we keep Auth0 for admin mode.
- Supporting `www.xxx.shibari.photo` initially. (Can be added later.)

## Key Decisions (Locked)

- **Routing**
  - Canonical host: `xxx.shibari.photo` maps to tenant `xxx`.
  - Normalize host by: lowercasing + stripping port.
  - Reject `www.xxx.shibari.photo` and unknown hosts for now.

- **HTTPS**
  - All traffic should end up on **HTTPS**.
  - Heroku ACM manages certificates for `*.shibari.photo`.
  - Application may defensively redirect HTTP → HTTPS when appropriate.

- **Orchestrator contract**
  - Use **Option B**: *single call* returns app type + runtime config for a host.
  - Publisher V2 also calls orchestrator to resolve credentials via **Option A**: `credentials_ref` → provider credentials.

- **Dropbox credential strategy**
  - Orchestrator returns **refresh token only** for Dropbox.
  - Publisher V2 holds global `DROPBOX_APP_KEY`/`DROPBOX_APP_SECRET` (shared Dropbox OAuth app).

- **Config caching**
  - TTL is **stable** (minutes), default target: **10 minutes** (tunable).

## Domain & DNS / Heroku Setup

### DNS (Hetzner)
- `CNAME *` for `shibari.photo` points to the Heroku app’s DNS target.

### Heroku
- The Heroku app must have custom domain: `*.shibari.photo` (single wildcard).
- Enable Heroku **ACM** for TLS cert management.
- Ensure app respects forwarded headers (Heroku router).

## Multi‑Tenant Architecture

### High-level flow

1. Request arrives to Publisher V2 web app with `Host: xxx.shibari.photo`.
2. Publisher V2 extracts tenant slug `xxx`.
3. Publisher V2 calls platform-orchestrator runtime endpoint (cached by tenant):
   - returns `app_type`, `config_version`, `ttl_seconds`, and structured `config`.
4. If `app_type != publisher_v2`, respond with 404 (tenant is for a different app type).
5. Publisher V2 resolves storage credentials (cached by `credentials_ref` + version).
6. Publisher V2 runs the web route handler using tenant-scoped services:
   - storage provider adapter
   - AI config + publishers config
7. All reads/writes (images, sidecars, archive moves) are scoped to the tenant’s configured storage paths.

### Execution plane responsibilities (Publisher V2)
- Tenant resolution and validation
- Runtime config fetch + caching
- Credential resolution + caching
- Stateless execution of V2 workflow per request
- Logging/telemetry tagged with `tenant` + `config_version` + correlation id

### Control plane responsibilities (platform-orchestrator)
- Domain → tenant/app binding
- Tenant/app runtime config generation
- Provider credential storage and secure retrieval
- OAuth onboarding flows (e.g., “Connect Dropbox”) and token lifecycle
- Auditing of runtime config + credential access

## Orchestrator API Contract (Option B + Credential Resolution)

This epic’s “contract” sections are aligned to the orchestrator’s published integration guide:

- `docs_v2/02_Specifications/ORCHESTRATOR_SERVICE_API_INTEGRATION_GUIDE.md`

### Canonical contract sources (locked)

The orchestrator PM clarified in `platform-orchestrator#32` that:

- The **canonical lock-in contract** is the orchestrator **Contract Appendix** and the canonical v2 example payload (`platform-orchestrator#31`).
- The `publisher-v2-service-api.md` file in the orchestrator repo is treated as an integration guide, but **Publisher must implement to the Contract Appendix / schema v2**.

Publisher must treat those artifacts as the source of truth for schema v2 fields and conventions.

### 1) Runtime config by host (single call)

**Endpoint (example):** `GET /v1/runtime/by-host?host=xxx.shibari.photo`  
**Auth:** service-to-service bearer token (rotatable)  
**Response (shape):**

- `tenant`: `"xxx"`
- `app_type`: `"publisher_v2"` (or other)
- `config_version`: string (monotonic or UUID; changes on any config update)
- `ttl_seconds`: int (e.g. 600)
- `config`: object (structured; see below)

**Publisher requirements (Feature 05 / orchestrator guide):**
- Host must be normalized: lowercase, strip `:port`, strip trailing `.`
- Reject host shapes without calling orchestrator (return 404 in Publisher):
  - IPv4/IPv6 literals, `localhost`, `www.*`, double-dot/empty label
- Treat orchestrator `404` as privacy-preserving “not found” (do not leak whether tenant exists).

### 2) Credential resolution by reference (Option A)

**Endpoint (actual):** `POST /v1/credentials/resolve`  
**Auth:** service-to-service bearer token  
**Request requirements (Feature 06 / orchestrator guide):**
- Header: `X-Tenant: <tenant>` (must match tenant derived from Host)
- Body: `{ "credentials_ref": "opaque-ref" }`

**Response (Dropbox example):**

- `provider`: `"dropbox"`
- `version`: string/uuid
- `refresh_token`: string
- `expires_at`: null

### 3) Error semantics

- Runtime endpoint:
  - 404: tenant not found / no binding for host
  - 409: host is bound but app type mismatch (optional; 404 is also acceptable)
  - 429/5xx: transient issues
- Credentials endpoint:
  - 404: missing credentials
  - 403: authorization failure (wrong service token)
  - 429/5xx: transient issues

Publisher V2 should treat orchestrator failures as **safe failure** (no publishing).

## Contract decisions confirmed by orchestrator PM (Issue #32)

These items are treated as **locked conventions** for Publisher implementation:

- **Doc canonicalization**
  - Canonical contract is the orchestrator Contract Appendix + v2 example payload.

- **Email server mapping**
  - Runtime config uses: `config.email_server.{host,port,use_tls,from_email,username,password_ref}`.
  - Publisher behavior:
    - `if use_tls: starttls()` else skip
    - `login_user = username or from_email` (supports `username != from_email`)

- **Publishers enablement convention**
  - Orchestrator may include entries with `enabled=false` for visibility.
  - Publisher must filter by `enabled=true` and treat disabled entries as no-ops.

- **Caching semantics**
  - Treat `config_version` as **opaque**; use it for cache invalidation only.
  - `ttl_seconds` is currently a **global setting** (default 600), not per-tenant.

- **Privacy-preserving 404 stance**
  - No machine-readable “reason” is currently emitted for `404` (unknown/disabled/misconfigured).
  - Operator workflow is via correlation (`X-Request-Id` in Publisher requests) + orchestrator audit logs (and optionally the orchestrator operator UI).

- **Request ID correlation**
  - Orchestrator includes `X-Request-Id` in audit logs but **does not echo it back** in response headers/body.
  - Publisher should generate and log the request id and correlate via orchestrator audit logs.

## Publisher Needs vs Current Orchestrator Guide (Delta / Change Request)

The current integration guide (`docs_v2/02_Specifications/ORCHESTRATOR_SERVICE_API_INTEGRATION_GUIDE.md`) is a solid start, but **it only specifies `config.features` + `config.storage`** in runtime config, and **only Dropbox** in credentials resolution.

With Feature 021 shipped (env-first consolidated config), Publisher V2 now has a clear, typed configuration surface that must be satisfiable via orchestrator for true multi-tenant runtime.

### P0 (Must-have) — Runtime config must include additional non-secret blocks

Publisher needs the runtime endpoint to return these **non-secret** config blocks (all secrets remain references):

- **`config.publishers`**: the equivalent of Feature 021 `PUBLISHERS` (non-secret), e.g. telegram `channel_id`, email/fetlife `recipient`, instagram `username`.
- **`config.email_server`**: the equivalent of Feature 021 `EMAIL_SERVER` (non-secret): `smtp_server`, `smtp_port`, `sender`.
- **`config.ai`**: the equivalent of Feature 021 `OPENAI_SETTINGS` **excluding secrets**: models, prompts, sd-caption flags.
- **`config.captionfile`**: Feature 021 `CAPTIONFILE_SETTINGS`: `extended_metadata_enabled`, `artist_alias`.
- **`config.confirmation`**: Feature 021 `CONFIRMATION_SETTINGS`: confirmation behavior fields.
- **`config.content`**: Feature 021 `CONTENT_SETTINGS`: `hashtag_string`, `archive`, `debug`.

Rationale: without these blocks, Publisher cannot reconstruct the same behavior we already support in single-tenant env-first deployments.

### P0 (Must-have) — Credentials resolution must support more than Dropbox

The credentials endpoint is currently documented only for Dropbox refresh tokens. For multi-tenant Publisher, orchestrator must be able to return **provider/app secrets** via opaque references, e.g.:

- **OpenAI**: API key (or equivalent) per tenant/app.
- **Telegram**: bot token.
- **Email/SMTP**: password (app password).
- **Instagram**: credential material (exact strategy TBD; may be password/session token/cookie bundle).
- **Storage providers**: Dropbox refresh token (already), plus future providers.

Publisher requirement: runtime config must reference secrets via **opaque refs**, not inline values (Feature 021 security rule: “secrets are separate, rotatable, auditable”).

### P1 (Recommended) — Explicit secret refs in runtime config

To keep runtime config non-secret but still self-describing, we recommend runtime config includes explicit refs, for example:

- `config.storage.credentials_ref` (already present)
- `config.ai.credentials_ref` (e.g., OpenAI key ref)
- `config.publishers[].credentials_ref` (e.g., telegram bot token ref, instagram ref, etc.)
- `config.email_server.password_ref` (or reuse `config.publishers[]` ref for email)

This avoids hidden conventions and lets Publisher fail fast when a required ref is missing.

### P1 (Recommended) — Response examples and schema versioning for the expanded config

We should extend the orchestrator “schema_version 1” example to include the above blocks (still no secrets). This allows Publisher to validate using typed models and gives orchestrator a clear contract to implement and evolve.

### P2 (Nice-to-have) — Reduce query-string leakage risk for host lookups

The guide currently uses `GET /v1/runtime/by-host?host=...` and cautions about query-string logging. If this proves hard to guarantee at the infra layer, consider additionally supporting:

- `POST /v1/runtime/by-host` with JSON body `{ "host": "<normalized_host>" }`

This is optional but can materially reduce accidental host leakage in access logs.

## Publisher V2 Runtime Config Schema (Conceptual)

> Orchestrator stores structured config. Publisher V2 validates it into typed models.
> Only required blocks are present for the given tenant/app.

### `features`
- `publish_enabled: bool`
- `analyze_caption_enabled: bool`
- `keep_enabled: bool`
- `remove_enabled: bool`
- `auto_view_enabled: bool` (optional)
- `mode: "review" | "publish"` (optional, derived from publish_enabled)

### `ai` (optional overrides)
- `vision_model: str`
- `caption_model: str`
- `sd_caption_enabled: bool`
- `sd_caption_single_call_enabled: bool`
- `rate_per_minute: int`
- optional prompt overrides

### `storage`
- `provider: "dropbox" | "gdrive" | "s3" | ...`
- `credentials_ref: str`
- `paths`:
  - `root: str` (provider-specific)
  - `archive: str`
  - `keep: str`
  - `remove: str`

### `publishers` (optional sections, present only when enabled)
- `telegram`: bot token ref / channel id, etc.
- `email`: sender/recipient refs, smtp settings, FetLife rules
- `instagram`: credentials refs, session strategy

## Auth0 + Multi-Subdomain (Admin Mode)

### Requirements
- Admin mode must work on `xxx.shibari.photo` for any tenant `xxx`.
- We do not want to register a callback URL per tenant.

### Recommended approach
- Use **one canonical callback host** (e.g., `app.shibari.photo/auth/callback`) in Auth0.
- Set admin cookie with `Domain=.shibari.photo` so the session is valid across subdomains.
- Preserve “return to” destination using OIDC state (stored server-side or signed) so user returns to original `xxx.shibari.photo`.

### Web UI expectations
Non-admin users must not see admin-only controls (Feature 005/CR-005 guidelines remain).

## Caching Strategy (Stable TTL)

### Runtime config cache (Publisher V2)
- Key: `normalized_host` (recommended by orchestrator guide)
- Value: `{config_version, expires_at, config}`
- TTL: `ttl_seconds` from orchestrator (default target 600s / 10m).
- If config fetch fails:
  - If cached and not expired: use cached config
  - Else: return 503 and **do not** allow mutating operations

### Credentials cache (Publisher V2)
- Key: `credentials_ref` (and tenant context for safety)
- Value: `{version, expires_at, credential_payload}`
- TTL: use runtime TTL or a slightly shorter TTL
- If credential fetch fails: deny operations that require that provider
 - Credentials responses must be treated as secret material (`Cache-Control: no-store`); do not persist beyond process memory.

## Migration Plan (Phased, Low-Risk)

### Phase 0 — Document & align
- Align orchestrator + Publisher V2 on the Option B contract and credential resolution.
- Decide canonical callback host + cookie domain strategy for Auth0.

### Phase 1 — Tenant resolution (no behavior change)
- Add tenant parsing from `Host`.
- Support only one tenant initially (default mapping) to avoid regressions.

### Phase 2 — Orchestrator runtime config (read-only paths first)
- Implement runtime config fetch + caching.
- Use orchestrator config for read-only endpoints (e.g., list/random/thumbnail).

### Phase 3 — Provider credentials resolution (Dropbox refresh token only)
- Implement credentials lookup + caching for Dropbox.
- Instantiate Dropbox client per tenant using:
  - global app key/secret (Publisher V2 env)
  - tenant refresh token (from orchestrator)

### Phase 4 — Mutating actions multi-tenant
- Enable analyze/publish/keep/remove for orchestrator-backed tenants.
- Ensure strict safe-failure semantics when orchestrator is unavailable.

### Phase 5 — Decommission per-tenant Heroku apps
- Move remaining tenants to wildcard routing.
- Keep rollback path (temporary ability to run a dedicated app per tenant if required).

## Acceptance Criteria

- Visiting `https://xxx.shibari.photo/` loads the web UI and resolves tenant `xxx`.
- The web UI can show images for tenant `xxx` using the tenant’s configured storage provider and folder.
- Admin actions (analyze, publish, keep, remove) are:
  - Hidden to non-admin users
  - Authorized via Auth0 + admin cookie
  - Correctly scoped to tenant `xxx` storage paths
- Orchestrator outage behavior:
  - No mutating operations occur without a valid cached config+credentials
  - Service returns clear 503 errors for missing runtime config
- Tenant isolation:
  - No cross-tenant data leakage in responses, sidecars, archive moves, or logs
- Config caching:
  - Runtime config is not fetched on every request under normal operation (TTL honored)
  - `config_version` change invalidates cache promptly

## Risks & Mitigations

- **Risk:** wildcard domain not correctly added to Heroku (DNS works but app rejects host).  
  **Mitigation:** ensure `*.shibari.photo` is added as a Heroku domain and ACM is enabled.

- **Risk:** Auth0 callback/cookie mismatch across subdomains.  
  **Mitigation:** single callback host + cookie domain `.shibari.photo`; explicit tests.

- **Risk:** orchestrator dependency adds runtime fragility.  
  **Mitigation:** TTL caching + safe failure; readiness checks; clear observability.

- **Risk:** provider abstraction adds complexity.  
  **Mitigation:** implement Dropbox via interface first; add providers one-by-one with tight tests.

## Related Work

- Feature 020: Auth0 login (`docs_v2/08_Epics/002_web_admin_curation_ux/020_auth0_login/020_feature.md`)
- Feature 018: Web thumbnail optimization (`docs_v2/08_Epics/002_web_admin_curation_ux/018_thumbnail_preview_optimization/018_feature.md`)
- Feature 011: Heroku app cloning (legacy approach to reduce manual ops) (`docs_v2/08_Epics/004_deployment_ops_modernization/011_heroku_hetzner_app_cloning/011_feature.md`)

## Open Questions (to resolve during implementation)

- Canonical callback host name selection (e.g., `app.shibari.photo`) and DNS/TLS provisioning.
- Whether to support `www.xxx.shibari.photo` aliasing later.
- Whether to include tenant-specific admin allowlists (or keep global).
- Exact error codes for “host bound but wrong app type” (404 vs 409).


