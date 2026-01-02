# Publisher V2 ↔ Orchestrator — Service API (Expert Integration Guide)

This document is written for the **Publisher V2** team. It specifies **exactly** how to call the orchestrator’s **service-to-service** APIs introduced by Features 05–08.

Scope:

- Runtime config lookup by host (**non-secret**) — Feature 05
- Credential resolution by opaque reference (**secret**) — Feature 06
- Service auth rotation + rate limiting — Feature 07
- Audit logging expectations + safe logging surfaces — Feature 08

Status note:

- Publisher V2 now supports **schema v2 runtime config** and **multi-provider credential resolution** (Feature 022). This guide is the **service API** reference; for the end-to-end Publisher-side integration and mapping to V2 config models, see:
  - `docs_v2/08_Epics/001_multi_tenant_orchestrator_runtime_config/022_orchestrator_schema_v2_integration/022_feature.md`

Canonical source contract:

- `docs/03_Specifications/09_PublisherV2OrchestratorContractAppendix/README.md` (in `platform-orchestrator`)

Canonical field-level schema reference (for orchestrator GUI validation):

- `docs_v2/02_Specifications/ORCHESTRATOR_RUNTIME_CONFIG_SCHEMA_REFERENCE.md`

---

## 1) Base URL and route prefixes (important)

The orchestrator has multiple API surfaces. **Publisher must use the service endpoints under `/v1`**:

- Runtime config: `POST /v1/runtime/by-host` (**preferred**) with **GET fallback** on 405
- Credentials: `POST /v1/credentials/resolve`

Do not use `/api/v1` (that is for the orchestrator’s admin/browser API).

Publisher configuration should include:

- **`ORCHESTRATOR_BASE_URL`**: e.g. `https://<orchestrator-host>` (no trailing slash)
- **`ORCHESTRATOR_SERVICE_TOKEN`**: bearer token (see auth below)

---

## 2) Service-to-service authentication (Feature 07)

All service endpoints require:

- **Header**: `Authorization: Bearer <token>`

Rotation model:

- The orchestrator accepts a **primary** token and optionally a **secondary** token during rotation.
- Publisher should support **hot rotation** by allowing token refresh without restart (optional but recommended).

Failure semantics:

- `403` means missing/invalid token. Do not retry with the same token.
- `429` means rate limited (best-effort per-dyno limiter). Treat as transient (retry with backoff).

Security:

- Never log bearer tokens.
- Never include tokens in error messages.

---

## 3) Host normalization and tenant extraction (Feature 05)

Publisher **must** normalize the incoming request host exactly the same way the orchestrator does:

Normalization:

- lowercase
- strip `:port`
- strip trailing `.`
- treat leading/trailing whitespace as invalid

Reject these host shapes (do not call orchestrator; behave as “not found” / 404 in Publisher):

- IPv4 literals (e.g. `127.0.0.1`)
- IPv6 literals (e.g. `::1`, `[::1]`)
- `localhost`
- `www.*` (publisher should not request runtime by a `www` host)
- double-dot / empty label (e.g. `tenant..shibari.photo`)

Tenant extraction:

- For allowed hosts of the form `xxx.<base-domain>`, tenant is the **first label**: `tenant = "xxx"`.

---

## 4) Runtime config endpoint (Feature 05)

### Request

- **Method**: `POST` (**preferred**) with `GET` fallback on 405
- **Path**: `/v1/runtime/by-host`
- **POST body**: `{ "host": "<normalized_host>" }`
- **GET query** (fallback): `host=<normalized_host>`
- **Headers**:
  - `Authorization: Bearer <token>`
  - (recommended) `X-Request-Id: <uuid>` for correlation (Publisher-generated)

### Response (schema version 1; no secrets)

Top-level response:

```json
{
  "schema_version": 1,
  "tenant": "xxx",
  "app_type": "publisher_v2",
  "config_version": "sha256-hex",
  "ttl_seconds": 600,
  "config": {
    "features": {
      "publish_enabled": false,
      "analyze_caption_enabled": false,
      "keep_enabled": true,
      "remove_enabled": true,
      "auto_view_enabled": false
    },
    "storage": {
      "provider": "dropbox",
      "credentials_ref": "opaque-ref",
      "paths": {
        "root": "/some/root/path",
        "archive": "/some/root/path/archive",
        "keep": "/some/root/path/keep",
        "remove": "/some/root/path/remove"
      }
    }
  }
}
```

Notes:

- `config` is **non-secret** by design.
- `credentials_ref` is **sensitive-ish metadata**: treat it as a high-value identifier and avoid logging it.
- `config_version` is **sha256(canonical_json(config))**. Publisher should treat it as **opaque** and use it for caching/invalidations.
- `ttl_seconds` is a caching hint. Publisher may clamp it to a safe range.

### Response (schema version 2; no secrets)

Schema v2 extends the v1 response by adding additional **non-secret** config blocks that map to Publisher V2’s env-first configuration surface (Feature 021).

Publisher should treat:

- **All secrets** as references (`credentials_ref`, `password_ref`) and resolve them via `/v1/credentials/resolve`
- Unknown fields as forward-compatible (ignore / tolerate)

Additional `config` blocks in schema v2:

- `publishers[]`
- `email_server`
- `ai`
- `captionfile`
- `confirmation`
- `content`

For the detailed v2 field mapping and examples, see:

- `docs_v2/08_Epics/001_multi_tenant_orchestrator_runtime_config/022_orchestrator_schema_v2_integration/stories/02_schema_v2_parsing/022_02_schema-v2-parsing.md`

### Status codes

- `200`: tenant found and eligible for Publisher V2
- `404`: privacy-preserving “not found”
  - unknown host
  - disabled/suspended tenant
  - app type mismatch (reserved behaviour)
  - invalid host shape
- `403`: missing/invalid service token
- `429`: rate limited (retryable)
- `5xx`: transient/internal failures (retryable)

### Publisher caching guidance

Recommended in-memory cache key:

- `runtime_config:<normalized_host>` (or `runtime_config:<tenant>`, but host is safer if you ever support multiple hostnames per tenant)

Cache value:

- the entire response payload, plus `fetched_at`

Invalidation:

- Cache is valid until `fetched_at + ttl_seconds`.
- When expired, re-fetch. If the new `config_version` differs, treat it as a configuration change.

Negative caching:

- If you get `404`, you may cache “not found” for a short TTL (e.g. 30–60s) to reduce load, but do not persist it.

---

## 5) Credentials resolution endpoint (Feature 06)

This endpoint returns **secrets**. Treat responses as secret material.

### Request

- **Method**: `POST`
- **Path**: `/v1/credentials/resolve`
- **Headers**:
  - `Authorization: Bearer <token>`
  - `X-Tenant: <tenant>` (must match the tenant derived from the request Host)
  - (recommended) `X-Request-Id: <uuid>`
- **Body**:

```json
{ "credentials_ref": "opaque-ref" }
```

### Response headers (always on success)

- `Cache-Control: no-store`
- `Pragma: no-cache`

### Response payload (Dropbox v1)

```json
{
  "provider": "dropbox",
  "version": "sha256-hex",
  "refresh_token": "…",
  "expires_at": null
}
```

Notes:

- `expires_at` is `null` for Dropbox refresh tokens.
- `version` is `sha256(canonical_json(version_inputs))` where:

```json
{ "provider": "dropbox", "refresh_token": "...", "expires_at": null }
```

Even though `version` is a hash, treat it as **sensitive-adjacent** and avoid logging it with high cardinality unless needed.

### Status codes

- `200`: credentials resolved
- `400`: caller error (missing `X-Tenant` OR missing/invalid `credentials_ref` in body)
- `403`: missing/invalid service token
- `404`: unknown ref OR ref not authorized for `X-Tenant` (privacy-preserving)
- `429`: rate limited (retryable)
- `5xx`: transient/internal failures (retryable)

### Publisher handling guidance (secrets)

- Do **not** persist these credentials to disk.
- Keep in memory only as long as needed (process memory).
- Prefer caching in memory keyed by `(tenant, credentials_ref, version)` only if you have a strong reason; otherwise resolve on-demand.
- Always honor `no-store` semantics: do not write to caches that persist beyond process lifetime.

---

## 6) Retries, timeouts, and backoff (Publisher responsibilities)

Publisher should treat the orchestrator as a service dependency:

- **Timeouts**: use a bounded request timeout (e.g. 2–5s) and fail safely.
- **Retries**:
  - Retry on `429` and `5xx` with exponential backoff + jitter.
  - Do not retry on `400`, `403`, `404` (unless you have a good reason, e.g. transient host mismatch due to stale config).
- **Backoff suggestion** (example):
  - base 250ms, cap 5s, max 3 attempts, plus random jitter.

---

## 7) Safe logging and observability

Publisher must avoid creating new leakage surfaces:

Never log:

- `Authorization` header values (service tokens)
- `refresh_token`
- full `credentials_ref`
- query string `host=...` (prefer logging the normalized host/tenant separately, not the raw URL)

Recommended to log (structured):

- `request_id` (Publisher-generated; also send to orchestrator via `X-Request-Id`)
- `tenant`
- `config_version` (optional; avoid if too high-cardinality)
- `http_status`
- `latency_ms`
- `retries`

Orchestrator-side audit logging exists (Feature 08). Publisher should maximize correlation by always sending `X-Request-Id`.

Operational note:

- See `docs/09_Operations/2025-12-21-runtime-by-host-access-log-guidance.md` (in `platform-orchestrator`) for ingress guidance regarding query string logging.

---

## 8) End-to-end Publisher flow (reference)

For each incoming Publisher request:

1. Extract and normalize `Host`.
2. Derive `tenant`.
3. Fetch runtime config:
   - `GET /v1/runtime/by-host?host=<normalized_host>`
4. If 404 → respond as “tenant not found” (do not reveal whether tenant exists).
5. If 403/429/5xx → fail safely (e.g. 503) without leaking details; log correlation id.
6. Use returned `config` to determine behavior and obtain `credentials_ref`.
7. Resolve credentials when needed:
   - `POST /v1/credentials/resolve` with `X-Tenant` and body `credentials_ref`
8. Use the resolved Dropbox refresh token to obtain access tokens via Dropbox OAuth (Publisher-held app key/secret), then proceed with the workflow.


