# Story 02 — Schema V2 Parsing

**Feature ID:** 022  
**Story ID:** 022-02  
**Status:** Shipped  
**Date:** 2025-12-25

---

## Context / Scope

The orchestrator now returns schema v2 runtime config responses that include additional non-secret blocks beyond `features` and `storage`:

- `config.publishers[]` — publisher configurations
- `config.email_server` — SMTP server settings
- `config.ai` — OpenAI/AI settings
- `config.captionfile` — caption file settings
- `config.confirmation` — confirmation email settings
- `config.content` — content/hashtag settings

Publisher V2 must parse both v1 and v2 responses, mapping orchestrator blocks to existing Pydantic models from Feature 021.

**Parent feature:** [022_feature.md](../../022_feature.md)  
**Depends on:** Story 01 (Config Source Abstraction)

---

## Dependencies

| Story | Requirement |
|-------|-------------|
| 01 — Config Source Abstraction | `OrchestratorConfigSource` skeleton must exist |

---

## Behaviour

### Preconditions

- Story 01 is implemented (ConfigSource abstraction exists)
- Orchestrator is returning schema v2 responses (Features 10–12 shipped)
- Feature 021 Pydantic models exist

### Main Flow

1. Implement `OrchestratorConfigSource.get_config(host)`:
   - Normalize host using `normalize_host(host)`
   - Validate host using `validate_host(host)` → reject invalid shapes with 404
   - Call `GET /v1/runtime/by-host?host=<normalized_host>` (or POST, see Story 04)
   - Parse response JSON
   - Extract tenant from response (`response.tenant`)
   - Branch on `schema_version`:
     - **v1**: Parse `config.features` + `config.storage` only
     - **v2**: Parse all config blocks
   - Return `TenantConfig { tenant, config, credentials_refs }`

2. Create Pydantic models for orchestrator response:
   - `OrchestratorRuntimeResponse` — top-level response
   - `OrchestratorConfigV1` — schema v1 config shape
   - `OrchestratorConfigV2` — schema v2 config shape (extends v1)

3. Map orchestrator config blocks to Feature 021 models:

   | Orchestrator block | Feature 021 model | Notes |
   |--------------------|-------------------|-------|
   | `config.features` | `FeaturesConfig` | Direct mapping |
   | `config.storage` | `DropboxConfig` | Extract `paths`; see path mapping below |
   | `config.publishers[]` | `TelegramConfig`, `EmailConfig` | Type-based; see publisher mapping below |
   | `config.email_server` | `EmailConfig` (partial) | SMTP settings; see field mapping below |
   | `config.ai` | `OpenAIConfig` | Direct mapping |
   | `config.captionfile` | `CaptionFileConfig` | Direct mapping |
   | `config.confirmation` | `EmailConfig` (partial) | Confirmation fields only |
   | `config.content` | `ContentConfig` | Note: `archive` is boolean here |

4. **Email server field mapping** (orchestrator → Publisher V2):

   | Orchestrator (`email_server`) | Publisher V2 (`EmailConfig`) | Notes |
   |-------------------------------|------------------------------|-------|
   | `host` | `smtp_server` | Rename |
   | `port` | `smtp_port` | Rename |
   | `from_email` | `sender` | Rename |
   | `use_tls` | *(new field)* | If true → STARTTLS; assume true for MVP |
   | `username` | *(new field)* | Use `username or from_email` for login |
   | `password_ref` | → resolve to `password` | Via credential resolution |

5. **Publisher type mapping**:

   | Publisher `type` | Internal Config | `credentials_ref` | Notes |
   |------------------|-----------------|-------------------|-------|
   | `telegram` | `TelegramConfig` | Required → bot_token | Direct credential resolution |
   | `fetlife` | `EmailConfig` | `null` (intentional) | Uses `email_server.password_ref` for SMTP auth |
   | `instagram` | `InstagramConfig` | Optional | Not yet in orchestrator |

   > **FetLife publishers do NOT have their own `credentials_ref`**. They use the shared `email_server` to send emails to the FetLife upload address (recipient). The `password_ref` on `email_server` provides SMTP authentication.

6. **Publisher enabled filtering**:
   - Publishers with `enabled: false` must be **ignored** (not instantiated)
   - Publishers with `enabled: true` are instantiated if their required credentials resolve

7. **Content vs Storage archive clarification**:
   - `config.content.archive` → **boolean** (whether to archive after publish)
   - `config.storage.paths.archive` → **path string** (where to archive)
   - These are distinct fields; both are used

8. Handle `credentials_ref` fields:
   - `config.storage.credentials_ref` → store for later resolution
   - `config.ai.credentials_ref` → store for later resolution
   - `config.email_server.password_ref` → store for later resolution
   - `config.publishers[*].credentials_ref` → store for later resolution

5. Use `extra="allow"` on Pydantic models for forward compatibility (ignore unknown fields).

6. Implement **runtime config caching**:
   - Cache key: `normalized_host`
   - Cache value: `{config_version, expires_at, config}`
   - TTL: `ttl_seconds` from orchestrator response (default 600s)
   - Max size: `RUNTIME_CONFIG_CACHE_MAX_SIZE` (default 1000), LRU eviction
   - On cache miss or expiry: re-fetch from orchestrator
   - On fetch failure with valid cache: use cached config (log "stale serve")
   - On fetch failure without cache: raise `OrchestratorUnavailableError`
   - **Metrics:**
     - `runtime_config_cache_hit_total`
     - `runtime_config_cache_miss_total`
     - `runtime_config_cache_stale_serve_total`

### Alternative Flows

- **Schema v1 response**: If `schema_version == 1`, only parse `features` + `storage`; other blocks use fallback defaults:

| Missing block | Fallback behavior |
|---------------|-------------------|
| `features` | **REQUIRED** — fail fast if missing |
| `storage` | **REQUIRED** — fail fast if missing |
| `publishers[]` | No publishers enabled (empty list) |
| `email_server` | Email-based publishers disabled |
| `ai` | AI features disabled (`analyze_caption_enabled` forced false) |
| `captionfile` | Use defaults (`extended_metadata_enabled=false`) |
| `confirmation` | Use defaults |
| `content` | Use defaults (`archive=true`, `debug=false`) |

### Error Flows

- **Invalid JSON**: Raise `ConfigurationError` with details
- **Missing required fields**: Raise `ConfigurationError` with field path
- **Unexpected app_type**: Log warning and return 404-equivalent (tenant not found for this app)
- **Orchestrator 404**: Raise `TenantNotFoundError`
- **Orchestrator 5xx**: Raise `OrchestratorUnavailableError` (retryable)

---

## Acceptance Criteria

- [ ] `OrchestratorConfigSource.get_config()` calls `/v1/runtime/by-host` with normalized host
- [ ] Schema v1 responses are correctly parsed into `ApplicationConfig`
- [ ] Schema v2 responses are correctly parsed with all config blocks
- [ ] Email server fields are mapped correctly (`host`→`smtp_server`, `port`→`smtp_port`, `from_email`→`sender`)
- [ ] Publishers with `enabled: false` are filtered out (not instantiated)
- [ ] Publishers with `enabled: true` are instantiated with their config
- [ ] FetLife publishers with `credentials_ref: null` are handled correctly (use `email_server.password_ref`)
- [ ] `config.content.archive` (boolean) is distinguished from `config.storage.paths.archive` (path)
- [ ] Unknown fields are ignored (`extra="allow"`)
- [ ] `credentials_ref` values are stored for later resolution (not resolved in this story)
- [ ] `config_version` and `ttl_seconds` are used for runtime config caching
- [ ] Runtime config cache returns cached value on cache hit without API call
- [ ] Runtime config cache re-fetches on expiry or `config_version` change
- [ ] Runtime config cache has max size limit with LRU eviction
- [ ] Runtime config cache metrics are exposed (hit/miss/stale_serve counters)
- [ ] Schema v1 fallback: missing optional blocks use defaults (not error)
- [ ] Schema v1 fallback: missing `features` or `storage` raises error
- [ ] Orchestrator 404 raises `TenantNotFoundError`
- [ ] Orchestrator 5xx raises `OrchestratorUnavailableError`
- [ ] Unit tests cover v1 and v2 parsing with sample payloads
- [ ] Unit tests verify publisher enabled filtering
- [ ] Unit tests verify email server field mapping
- [ ] No secrets or `credentials_ref` values appear in logs

---

## Testing

### Manual Testing

1. Point Publisher at orchestrator staging with a v2-enabled tenant → verify full config loads
2. Point Publisher at orchestrator with a v1-only tenant → verify features + storage load, others fallback
3. Test with unknown host → verify 404 behavior

### Automated Tests

Add/extend tests under `publisher_v2/tests/config/`:

- `test_orchestrator_config_source.py`:
  - `test_get_config_parses_schema_v1`
  - `test_get_config_parses_schema_v2_full`
  - `test_get_config_ignores_unknown_fields`
  - `test_get_config_extracts_credentials_refs`
  - `test_get_config_raises_tenant_not_found_on_404`
  - `test_get_config_raises_unavailable_on_5xx`
  - `test_get_config_maps_publishers_by_type`
  - `test_get_config_filters_disabled_publishers`
  - `test_get_config_maps_email_server_fields`
  - `test_fetlife_publisher_uses_email_server_password`
  - `test_content_archive_bool_vs_storage_paths_archive_string`

Add fixtures with sample v1 and v2 response payloads (use issue #31 as canonical example).

---

## Implementation Notes

### Files to Create/Modify

- **Create**: `publisher_v2/src/publisher_v2/config/orchestrator_models.py`
  - `OrchestratorRuntimeResponse`
  - `OrchestratorConfigV1`
  - `OrchestratorConfigV2`
  - `OrchestratorPublisher` (discriminated union by `type`)

- **Modify**: `publisher_v2/src/publisher_v2/config/source.py`
  - Implement `OrchestratorConfigSource.get_config()`

- **Create**: `publisher_v2/src/publisher_v2/config/orchestrator_client.py`
  - HTTP client wrapper for orchestrator API calls
  - Include `X-Request-Id` header for correlation

### Schema V2 Response Shape (Reference from Issue #31)

```json
{
  "schema_version": 2,
  "tenant": "<tenant>",
  "app_type": "publisher_v2",
  "config_version": "<sha256-hex>",
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
      "credentials_ref": "<opaque-ref>",
      "paths": {
        "root": "/Photos/<tenant>/<year>",
        "archive": "/Photos/<tenant>/<year>/archive",
        "keep": "/Photos/<tenant>/<year>/keep",
        "remove": "/Photos/<tenant>/<year>/remove"
      }
    },
    "publishers": [
      {
        "id": "telegram-1",
        "type": "telegram",
        "enabled": true,
        "credentials_ref": "<opaque-ref>",
        "config": { "channel_id": "<channel-id>" }
      },
      {
        "id": "fetlife-2",
        "type": "fetlife",
        "enabled": true,
        "credentials_ref": null,
        "config": {
          "recipient": "<id>@upload.fetlife.com",
          "subject_mode": "normal",
          "caption_target": "subject"
        }
      }
    ],
    "email_server": {
      "host": "smtp.example.com",
      "port": 587,
      "use_tls": true,
      "from_email": "user@example.com",
      "username": null,
      "password_ref": "<opaque-ref>"
    },
    "ai": {
      "credentials_ref": "<opaque-ref>",
      "vision_model": "gpt-4o",
      "caption_model": "gpt-4o-mini",
      "system_prompt": "<prompt>",
      "role_prompt": "<prompt>",
      "sd_caption_enabled": true,
      "sd_caption_single_call_enabled": true
    },
    "captionfile": {
      "artist_alias": "<alias>",
      "extended_metadata_enabled": true
    },
    "confirmation": {
      "confirmation_to_sender": true,
      "confirmation_tags_count": 5,
      "confirmation_tags_nature": "<nature>"
    },
    "content": {
      "archive": true,
      "debug": false,
      "hashtag_string": ""
    }
  }
}
```

**Key observations:**
- `publishers[type=fetlife].credentials_ref` is `null` — this is intentional; FetLife uses `email_server.password_ref`
- `email_server.host/port/from_email` map to Publisher's `smtp_server/smtp_port/sender`
- `content.archive` is a **boolean** (whether to archive), not a path

### Repo Rules

- **Async hygiene**: Use `httpx.AsyncClient` for HTTP calls
- **Log redaction**: Use `log_json` / existing sanitization; never log `credentials_ref`
- **Safe failure**: If orchestrator is unavailable, fail without mutating state

---

## Change History

| Date | Change |
|------|--------|
| 2025-12-24 | Initial story draft |
| 2025-12-25 | Added email server field mapping, publisher enabled filtering, FetLife credential handling clarification |

