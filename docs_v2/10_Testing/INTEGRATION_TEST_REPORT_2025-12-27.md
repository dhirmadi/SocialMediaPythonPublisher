# Publisher V2 Integration Test Report

**Date:** 2025-12-27  
**Test Target:** Simulating requests to `https://vermont.shibari.photo`  
**Orchestrator:** Local instance at `http://localhost:8089`  
**Orchestrator Version:** Feature 17 (Tenant-Scoped Secrets) deployed

---

## Executive Summary

**Result: ✅ ALL TESTS PASSED (28/28)**

Integration testing confirms that Publisher V2 is fully compatible with the orchestrator's Feature 17 (Tenant-Scoped Secrets) update. All credential resolution paths work correctly, and the Publisher can successfully operate in multi-tenant orchestrated mode.

| Metric | Value |
|--------|-------|
| Total Tests | 28 |
| Passed | 28 |
| Failed | 0 |
| Pass Rate | **100%** |

---

## Test Environment

```
Orchestrator URL:     http://localhost:8089
Orchestrator Feature: 17 (Tenant-Scoped Secrets)
Test Tenant:          vermont.shibari.photo
Service Token:        eg6vl6NRsfMs... (primary)
Schema Version:       2
Timestamp:            2025-12-27T12:16:52
```

---

## Orchestrator Context (GitHub Issue #34)

The orchestrator was recently updated with **Feature 17: Tenant-Scoped Secrets**:

### Key Changes (from platform-orchestrator#34)
- **New tables**: `tenants`, `tenant_secrets`
- **Credential resolution** now decrypts from `tenant_secrets(tenant_id=instance.tenant_id)` instead of `user_secrets(user_id=instance.owner_id)`
- **Tenant binding**: enforced at query time via `CredentialRef → Instance → Tenant` with `Tenant.slug == X-Tenant`
- **Migration invariant**: `Tenant.slug == Instance.name`

### Impact on Publisher
- **No changes required** — The orchestrator's API contract (`POST /v1/credentials/resolve`) remains unchanged
- Publisher's existing `X-Tenant` header usage already aligns with the tenant-scoped resolution
- All 4 credential providers (dropbox, openai, telegram, smtp) continue to work

---

## Test Results by Category

### 1. Orchestrator API Tests (11 tests)

| Test | Result | Latency | Details |
|------|--------|---------|---------|
| Orchestrator connectivity | ✅ PASS | 14ms | Server responded with 403 |
| Runtime config GET | ✅ PASS | 229ms | tenant=vermont, schema_v=2 |
| Runtime config POST (preferred) | ✅ PASS | 165ms | POST supported |
| Credential resolution (dropbox) | ✅ PASS | 295ms | has_refresh_token=True, no-store=True |
| Credential resolution (openai) | ✅ PASS | 192ms | has_api_key=True, no-store=True |
| Credential resolution (telegram) | ✅ PASS | 192ms | has_bot_token=True, no-store=True |
| Credential resolution (smtp) | ✅ PASS | 190ms | has_password=True, no-store=True |
| Unknown host returns 404 | ✅ PASS | 4ms | Privacy-preserving |
| Missing X-Tenant returns 400 | ✅ PASS | 1ms | Correctly rejected |
| Invalid credentials_ref returns 404 | ✅ PASS | 97ms | Privacy-preserving |
| Tenant mismatch returns 404 | ✅ PASS | 98ms | Privacy-preserving |

**Key Observations:**
- All 4 credential providers resolve successfully with the new tenant-scoped secrets
- Latency is acceptable (~190-295ms for credential resolution)
- Privacy-preserving 404s work correctly for all error cases

### 2. Publisher Client Tests (4 tests)

| Test | Result | Latency | Details |
|------|--------|---------|---------|
| OrchestratorClient.get_runtime_by_host | ✅ PASS | 163ms | tenant=vermont, schema_v=2 |
| OrchestratorClient raises TenantNotFoundError | ✅ PASS | 5ms | Exception raised correctly |
| OrchestratorClient.resolve_credentials | ✅ PASS | 193ms | provider=dropbox |
| OrchestratorClient raises CredentialResolutionError | ✅ PASS | 98ms | Exception raised correctly |

**Key Observations:**
- Publisher's `OrchestratorClient` correctly handles all orchestrator responses
- Exception hierarchy (`TenantNotFoundError`, `CredentialResolutionError`) works as designed

### 3. Config Source Tests (2 tests)

| Test | Result | Latency | Details |
|------|--------|---------|---------|
| ConfigSource factory (orchestrator mode) | ✅ PASS | 18ms | is_orchestrated=True |
| ConfigSource.get_config | ✅ PASS | 348ms | host=vermont.shibari.photo, has_config=True |

**Key Observations:**
- `OrchestratorConfigSource` correctly initializes and fetches runtime config
- Config parsing produces valid `ApplicationConfig` with all blocks populated

### 4. Web Service Tests (5 tests)

| Test | Result | Details |
|------|--------|---------|
| WebImageService orchestrated mode | ✅ PASS | is_orchestrated=True |
| WebImageService config loaded | ✅ PASS | has_config=True |
| WebImageService storage (eager) | ✅ PASS | DropboxStorage initialized |
| WebImageService AI (lazy) | ✅ PASS | ai_service=None initially (correct lazy behavior) |
| WebImageService features | ✅ PASS | publish=False, analyze=False, keep=True |

**Key Observations:**
- `WebImageService` correctly enters orchestrated mode
- Storage is eagerly initialized (as designed)
- AI service remains `None` until first analysis request (lazy initialization)

### 5. Host Utilities Tests (3 tests)

| Test | Result | Details |
|------|--------|---------|
| Host normalization | ✅ PASS | 3 cases tested |
| Host validation | ✅ PASS | 4 cases tested |
| Tenant extraction | ✅ PASS | vermont.shibari.photo → vermont |

### 6. Caching Tests (3 tests)

| Test | Result | Details |
|------|--------|---------|
| RuntimeConfigCache | ✅ PASS | LRU+TTL working |
| CredentialCache | ✅ PASS | In-memory cache working |
| SingleFlight (thundering herd) | ✅ PASS | 3 concurrent calls → 1 actual call |

---

## Runtime Config Received

The orchestrator returned a complete schema v2 configuration:

```json
{
  "schema_version": 2,
  "tenant": "vermont",
  "app_type": "publisher_v2",
  "config_version": "66564179f7c7f244...",
  "ttl_seconds": 0,
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
      "credentials_ref": "9d68e73f...",
      "paths": { "root": "/Photos/Tati/2025_Vermont", ... }
    },
    "publishers": [
      { "type": "telegram", "enabled": true, "credentials_ref": "7b0208a7..." },
      { "type": "fetlife", "enabled": true, "credentials_ref": null }
    ],
    "email_server": {
      "host": "smtp.gmail.com",
      "port": 587,
      "password_ref": "610eafa6...",
      "use_tls": true
    },
    "ai": {
      "credentials_ref": "3d9dbfb4...",
      "vision_model": "gpt-4o",
      "caption_model": "gpt-4o-mini"
    },
    "captionfile": { "extended_metadata_enabled": true },
    "confirmation": { "confirmation_to_sender": true },
    "content": { "archive": true }
  }
}
```

---

## Credential Resolution Summary

| Provider | Credential Ref | Resolved Field | Status |
|----------|---------------|----------------|--------|
| Dropbox | `9d68e73f...` | `refresh_token` | ✅ |
| OpenAI | `3d9dbfb4...` | `api_key` | ✅ |
| Telegram | `7b0208a7...` | `bot_token` | ✅ |
| SMTP | `610eafa6...` | `password` | ✅ |

All credentials were resolved with:
- `Cache-Control: no-store` header
- `Pragma: no-cache` header

---

## What Works ✅

1. **Runtime Config Retrieval**
   - GET and POST both work
   - Schema v2 fully parsed
   - All config blocks present (features, storage, publishers, email_server, ai, captionfile, confirmation, content)

2. **Credential Resolution**
   - All 4 providers work correctly (dropbox, openai, telegram, smtp)
   - Tenant-scoped secrets (Feature 17) resolved correctly
   - No-store headers present for security

3. **Error Handling**
   - Unknown host → 404 (privacy-preserving)
   - Missing X-Tenant → 400
   - Invalid credentials_ref → 404 (privacy-preserving)
   - Tenant mismatch → 404 (privacy-preserving)

4. **Publisher Integration**
   - ConfigSource abstraction works
   - WebImageService initializes correctly in orchestrated mode
   - Lazy AI initialization works
   - Eager storage initialization works

5. **Caching**
   - RuntimeConfigCache functional
   - CredentialCache functional
   - SingleFlight pattern prevents thundering herd

---

## What Fails ❌

**Nothing fails.** All 28 tests passed.

---

## What Needs to Be Fixed

**No fixes required in Publisher V2.** The integration is fully compatible with the orchestrator's Feature 17 update.

---

## Observations & Notes

### 1. TTL is 0
The orchestrator returns `ttl_seconds: 0`, meaning no caching TTL hint. Publisher uses its default TTL (~600 seconds). This is acceptable but could be improved on the orchestrator side.

### 2. Publishers Array Format
The orchestrator returns `config.publishers` as an array, not a dictionary. Publisher handles this correctly.

### 3. Feature Toggles
The tenant has `publish_enabled: false` and `analyze_caption_enabled: false`, which means:
- Publishing is disabled
- AI analysis is disabled
- Only Keep/Remove curation is enabled

This is a tenant configuration choice, not a bug.

### 4. FetLife Publisher
The `fetlife` publisher has `credentials_ref: null`, meaning it uses the shared email_server credentials (as expected for email-based publishing).

---

## Conclusion

**Publisher V2 is fully compatible with the orchestrator's Feature 17 (Tenant-Scoped Secrets) update.**

No code changes are required in the Publisher codebase. The integration test confirms:
- ✅ Runtime config retrieval works
- ✅ All 4 credential providers resolve correctly
- ✅ Error handling is correct
- ✅ WebImageService initializes properly in orchestrated mode
- ✅ Caching mechanisms function correctly

**Recommended:** This integration can be deployed to production.

---

*Report generated: 2025-12-27T12:17:00Z*  
*Test framework: Custom async integration tests (Python 3.12 + httpx)*  
*Publisher version: Feature 022 branch*

