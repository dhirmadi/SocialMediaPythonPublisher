# Orchestrator Runtime Config Schema Reference — Publisher V2 (GUI Validation Contract)

Version: 1.0  
Last Updated: December 30, 2025

This document is the **canonical, field-level contract** for the **orchestrator-managed runtime configuration** consumed by **Publisher V2**.  
It is intended for the **orchestrator team** to build an end-user GUI with **explicit validation**.

Scope:

- Runtime config envelope returned from `/v1/runtime/by-host` (**non-secret**)
- Schema v2 `config` blocks, their **required/optional** fields, and **allowed values**
- Credentials resolution responses from `/v1/credentials/resolve` (**secret**, never stored in runtime config)

Not in scope:

- Host normalization rules (see `ORCHESTRATOR_SERVICE_API_INTEGRATION_GUIDE.md`)
- Auth, rate limiting, retries (see `ORCHESTRATOR_SERVICE_API_INTEGRATION_GUIDE.md`)

---

## 1) High-level rules (non-negotiable)

1. **No secrets in runtime config**  
   Runtime config must not contain secret material (OpenAI API keys, refresh tokens, SMTP passwords, Telegram bot tokens).
2. **Secrets are references**  
   Secrets are delivered only via `/v1/credentials/resolve` using:
   - `credentials_ref` (general secret reference)
   - `password_ref` (SMTP password reference; still resolved via `/v1/credentials/resolve`)
3. **Publisher V2 currently supports only these orchestrator-managed publishers**:
   - `telegram`
   - `fetlife` (implemented via SMTP/email)

   Other publisher types may exist in orchestrator, but **Publisher V2 ignores them** today.
4. **“Enabled” is authoritative**  
   The GUI must prevent enabling an item unless all of its required fields are valid.

---

## 2) Endpoints (service API surface)

Canonical integration guide:

- `docs_v2/02_Specifications/ORCHESTRATOR_SERVICE_API_INTEGRATION_GUIDE.md`

Publisher behavior (current implementation):

- Runtime config lookup:
  - **Preferred**: `POST /v1/runtime/by-host` with body `{ "host": "<normalized_host>" }`
  - **Fallback**: `GET /v1/runtime/by-host?host=<normalized_host>` (only if POST returns 405)
- Credentials resolution:
  - `POST /v1/credentials/resolve` with:
    - header `X-Tenant: <tenant>`
    - body `{ "credentials_ref": "<opaque-ref>" }`

---

## 3) Runtime response envelope (schema v2)

Publisher expects the orchestrator to return this envelope:

| Field | Type | Required | Allowed / Notes |
|------|------|----------|-----------------|
| `schema_version` | int | ✅ | **2** for schema v2 (Publisher still supports v1 for backward compatibility) |
| `tenant` | string | ✅ | Tenant slug returned by orchestrator (Publisher treats as opaque string) |
| `app_type` | string | ✅ | Must be **`"publisher_v2"`** |
| `config_version` | string | ✅ | Opaque version token; changes whenever config changes |
| `ttl_seconds` | int | ✅ | Cache TTL in seconds (default 600). Must be positive. |
| `config` | object | ✅ | Schema v2 config object (next section) |

### 3.1 Caching semantics (important for GUI + operator expectations)

- `ttl_seconds` controls Publisher’s in-memory cache lifetime per host.
- Publisher may serve **stale cached config** when orchestrator is temporarily unavailable.

---

## 4) `config` object (schema v2)

Schema v2 extends schema v1 by including additional non-secret blocks needed for full Publisher operation.

Top-level required blocks:

- `features` (required)
- `storage` (required)

Note:

- Some admin UIs edit individual non-secret blocks (e.g., `ai`, `publishers`, `email_server`) in isolation.  
  This document describes the **full runtime payload** Publisher consumes; the orchestrator’s `/v1/runtime/by-host` response must still include `features` and `storage`.

Additional blocks (schema v2):

- `publishers` (optional array; defaults to empty)
- `email_server` (optional; required when enabling `fetlife`)
- `ai` (optional; required when enabling AI analysis)
- `captionfile` (optional; **required when enabling AI analysis**)
- `confirmation` (optional; **required when enabling AI analysis**)
- `content` (optional; **platform-managed defaults** — do not expose to end users)

---

## 4.0) Feature ↔ configuration dependency rules (GUI gating)

This section defines **when configuration blocks are required**, based on `config.features.*`.

Goal:

- The orchestrator GUI should **only ask for data that will be used**.
- The GUI must prevent enabling a feature unless the required config (and credential refs) are present and valid.

Terminology:

- **Required**: the GUI must not allow saving `enabled=true` / feature toggle `true` unless the required block/field is valid.
- **Optional**: may be omitted; Publisher will apply defaults.
- **Ignored**: may be present, but Publisher will not use it because the governing feature is off.

### 4.0.0 Recommended GUI flow (short)

Suggested order for an orchestrator admin UI that edits schema v2 blocks:

1. **Storage (required first)**
   - Collect `storage.provider="dropbox"`, `storage.credentials_ref`, and `storage.paths.root` (and optional `archive/keep/remove`).
2. **Features toggles**
   - Set `features.publish_enabled` and `features.analyze_caption_enabled` early; they control which sections should be shown/required.
3. **AI (only if analyze is enabled)**
   - If `analyze_caption_enabled=true`, require:
     - `ai.credentials_ref`
     - `captionfile` block (may be defaults)
     - `confirmation` block (may be defaults)
   - If `false`, hide/disable `ai`, `captionfile`, and `confirmation`.
4. **Publishers (only if publish is enabled)**
   - If `publish_enabled=true`, require at least one enabled publisher entry.
   - If `false`, hide/disable `publishers` and related secret refs (telegram/smtp).
5. **Email server (only if FetLife enabled)**
   - If an enabled `fetlife` publisher exists, require `email_server.host`, `email_server.from_email`, and `email_server.password_ref`.
6. **Optional finishing blocks**
   - `content` should be treated as **platform defaults** (not user-editable).

### 4.0.1 Always required (for any usable Publisher V2 tenant)

Even for “review-only” tenants, Publisher must still be able to **read images**. Therefore, these are always required in the full runtime payload:

- `config.features` (all fields present)
- `config.storage`:
  - `provider="dropbox"`
  - `credentials_ref` (non-empty string)
  - `paths.root` (absolute Dropbox path starting with `/`, no `..`)

Notes:

- Publisher currently resolves Dropbox credentials **eagerly** during config load. If `storage.credentials_ref` cannot be resolved, the tenant is effectively down.

### 4.0.2 AI captioning / analysis (`features.analyze_caption_enabled`)

If `config.features.analyze_caption_enabled = true`:

- **Required**
  - `config.ai.credentials_ref` (non-empty string; resolves to OpenAI API key via `/v1/credentials/resolve` provider `openai`)
- **Required**
  - `config.captionfile` (may use defaults; required so the orchestrator UI makes the dependency explicit)
  - `config.confirmation` (may use defaults; required so the orchestrator UI makes the dependency explicit)
- **Optional**
  - Other `config.ai` fields (`vision_model`, `caption_model`, prompts, `sd_caption_*`) to override defaults
- **Required (implicit gating)**
  - The orchestrator GUI should also ensure the referenced OpenAI credential exists for the tenant (via its own control-plane validation), but this is enforced at runtime by Publisher.

If `config.features.analyze_caption_enabled = false`:

- `config.ai`, `config.captionfile`, and `config.confirmation` may be omitted and should not be requested in the GUI.

### 4.0.3 Publishing (`features.publish_enabled`)

If `config.features.publish_enabled = true`:

- **Required**
  - `config.publishers` must contain **at least one** entry with `enabled=true` and a supported `type` (`telegram` or `fetlife`).
  - The GUI should require at least one enabled publisher; otherwise “publish” is enabled but has nowhere to publish.

If `config.features.publish_enabled = false`:

- `config.publishers` / `config.email_server` / publisher credential refs are **not required** and should not be requested.
- If present, they are effectively **ignored** because publishing is disabled.

### 4.0.4 Publisher-specific requirements (when that publisher is enabled)

The following rules apply only when BOTH:

- `config.features.publish_enabled = true`, AND
- there is a matching `config.publishers[]` entry with `enabled=true`.

#### A) Telegram publisher

Required:

- Publisher entry with:
  - `type="telegram"`
  - `enabled=true`
  - `credentials_ref` (non-empty string; resolves to provider `telegram`)
  - `config.channel_id` (non-empty string)

#### B) FetLife publisher (SMTP/email)

Required:

- Publisher entry with:
  - `type="fetlife"`
  - `enabled=true`
  - `credentials_ref` **must be null or omitted**
  - `config.recipient` (non-empty string)
  - Optional enums:
    - `config.caption_target ∈ {"subject","body","both"}`
    - `config.subject_mode ∈ {"normal","private","avatar"}`
- `config.email_server` present with:
  - `host` (non-empty string)
  - `from_email` (non-empty string)
  - `password_ref` (non-empty string; resolves to provider `smtp`)
  - `port` optional (defaults 587)

Notes:

- Confirmation behavior comes from `config.confirmation` (optional; defaults apply if omitted).

### 4.0.5 Curation (`features.keep_enabled` / `features.remove_enabled`)

If `keep_enabled=true` and/or `remove_enabled=true`:

- No additional config blocks are required beyond `config.storage`.
- If `storage.paths.keep/remove` are omitted, Publisher will derive defaults under `paths.root` (`keep` / `reject`).

### 4.0.6 Auto-view (`features.auto_view_enabled`)

- No additional config is required. This only affects web UI access rules.

### 4.1 `config.features`

| Field | Type | Required | Default | Notes |
|------|------|----------|---------|------|
| `publish_enabled` | bool | ✅ | `false` | Governs publishing (CLI + web) |
| `analyze_caption_enabled` | bool | ✅ | `false` | Governs AI analysis + caption generation |
| `keep_enabled` | bool | ✅ | `true` | Enables Keep curation action |
| `remove_enabled` | bool | ✅ | `true` | Enables Remove curation action |
| `auto_view_enabled` | bool | ✅ | `false` | Allows non-admin random viewing in web UI |

### 4.2 `config.storage`

| Field | Type | Required | Allowed / Notes |
|------|------|----------|-----------------|
| `provider` | string | ✅ | **Must be `"dropbox"`** (only supported provider today) |
| `credentials_ref` | string | ✅ | Opaque reference resolved to Dropbox refresh token |
| `paths` | object | ✅ | Storage paths (below) |

#### 4.2.1 `config.storage.paths`

| Field | Type | Required | Allowed / Notes |
|------|------|----------|-----------------|
| `root` | string | ✅ | Must start with `/`. Must not contain `..` path component. |
| `archive` | string \| null | ❌ | If relative, it is resolved under `root`. Default suffix: `archive`. Must not contain `..`. |
| `keep` | string \| null | ❌ | If relative, it is resolved under `root`. Default suffix: `keep`. Must not contain `..`. |
| `remove` | string \| null | ❌ | If relative, it is resolved under `root`. Default suffix: `reject`. Must not contain `..`. |

Notes:

- These are Dropbox paths (not local filesystem paths).
- `content.archive` (boolean) is different from `storage.paths.archive` (path).

### 4.3 `config.publishers[]`

Publisher list entries have this shape:

| Field | Type | Required | Notes |
|------|------|----------|------|
| `id` | string | ✅ | Stable identifier (used by orchestrator/UI) |
| `type` | string | ✅ | Allowed: `telegram`, `fetlife` |
| `enabled` | bool | ✅ | Default `true` |
| `credentials_ref` | string \| null | ❌ | Required for `telegram`; for `fetlife` it must be `null` **or omitted** |
| `config` | object | ✅ | Type-specific config block |

Important behavior:

- Publisher only consumes the **first enabled entry** of each supported type.
- Additional enabled entries of the same type are currently **ignored** by Publisher V2.

#### 4.3.1 Publisher type: `telegram`

Required:

- `enabled=true`
- `credentials_ref` (non-empty string)
- `config.channel_id` (non-empty string)

Config fields:

| Field | Type | Required | Notes |
|------|------|----------|------|
| `channel_id` | string | ✅ | Passed directly to Telegram API (`chat_id`) |

#### 4.3.2 Publisher type: `fetlife` (SMTP/email)

Required:

- `enabled=true`
- `credentials_ref=null` (**must be null or omitted**)  
  FetLife does not have a direct secret; SMTP auth is provided via `email_server.password_ref`.
- `config.recipient` (non-empty string)
- `email_server` present with `password_ref` + `from_email` + `host`

Config fields:

| Field | Type | Required | Allowed values |
|------|------|----------|----------------|
| `recipient` | string | ✅ | FetLife upload email address (string) |
| `caption_target` | string | ❌ | `subject`, `body`, `both` (default `subject`) |
| `subject_mode` | string | ❌ | `normal`, `private`, `avatar` (default `normal`) |

### 4.4 `config.email_server`

| Field | Type | Required | Notes |
|------|------|----------|------|
| `host` | string | ✅ | SMTP hostname |
| `port` | int | ❌ | Default `587` |
| `from_email` | string | ✅ | Sender email address |
| `password_ref` | string \| null | ❌ | **Required when any `fetlife` publisher is enabled** |
| `use_tls` | bool | ❌ | Default `true`. Present in schema; **currently ignored by Publisher** |
| `username` | string \| null | ❌ | Present in schema; **currently ignored by Publisher** |

Publisher behavior (current):

- Always uses **STARTTLS**.
- Always logs in with **username = `from_email`**.

Therefore:

- The GUI should assume STARTTLS and validate that the chosen SMTP server/port supports it.
- `use_tls` and `username` can be shown as “reserved / not yet used by Publisher V2”.

### 4.5 `config.ai`

| Field | Type | Required | Notes |
|------|------|----------|------|
| `credentials_ref` | string \| null | ✅* | Required to keep `features.analyze_caption_enabled=true` (otherwise Publisher disables AI) |
| `vision_model` | string \| null | ❌ | Must start with one of: `gpt-4`, `gpt-3.5`, `o1`, `o3` |
| `caption_model` | string \| null | ❌ | Must start with one of: `gpt-4`, `gpt-3.5`, `o1`, `o3` |
| `system_prompt` | string \| null | ❌ | Caption system prompt |
| `role_prompt` | string \| null | ❌ | Caption role/user prompt prefix |
| `sd_caption_enabled` | bool \| null | ❌ | Stable-Diffusion caption sidecar enable |
| `sd_caption_single_call_enabled` | bool \| null | ❌ | Prefer one-call `{caption, sd_caption}` |
| `sd_caption_model` | string \| null | ❌ | Optional override model (Publisher does not validate prefixes for this field today) |
| `sd_caption_system_prompt` | string \| null | ❌ | Optional override |
| `sd_caption_role_prompt` | string \| null | ❌ | Optional override |

### 4.6 `config.captionfile`

| Field | Type | Required | Default |
|------|------|----------|---------|
| `extended_metadata_enabled` | bool \| null | ❌ | `false` |
| `artist_alias` | string \| null | ❌ | `null` |

### 4.7 `config.confirmation`

| Field | Type | Required | Default |
|------|------|----------|---------|
| `confirmation_to_sender` | bool \| null | ❌ | `true` |
| `confirmation_tags_count` | int \| null | ❌ | `5` |
| `confirmation_tags_nature` | string \| null | ❌ | Default guidance string |

Notes:

- Publisher will treat negative values as “0 tags” (slice behavior).

### 4.8 `config.content`

Policy:

- `config.content` should be treated as **platform-managed defaults** and should **not** be end-user editable in the orchestrator GUI.
- Publisher has safe defaults if this block is omitted.

| Field | Type | Required | Default |
|------|------|----------|---------|
| `hashtag_string` | string \| null | ❌ | `""` |
| `archive` | bool \| null | ❌ | `true` |
| `debug` | bool \| null | ❌ | `false` |

---

## 5) Credential resolution responses (`POST /v1/credentials/resolve`)

The response is provider-discriminated and must include:

- `provider` (enum)
- `version` (string)

### 5.1 Provider: `dropbox`

| Field | Type | Required |
|------|------|----------|
| `provider` | `"dropbox"` | ✅ |
| `version` | string | ✅ |
| `refresh_token` | string | ✅ |
| `expires_at` | string \| null | ❌ |

### 5.2 Provider: `openai`

| Field | Type | Required |
|------|------|----------|
| `provider` | `"openai"` | ✅ |
| `version` | string | ✅ |
| `api_key` | string | ✅ |

### 5.3 Provider: `telegram`

| Field | Type | Required |
|------|------|----------|
| `provider` | `"telegram"` | ✅ |
| `version` | string | ✅ |
| `bot_token` | string | ✅ |

### 5.4 Provider: `smtp`

| Field | Type | Required |
|------|------|----------|
| `provider` | `"smtp"` | ✅ |
| `version` | string | ✅ |
| `password` | string | ✅ |

---

## 6) Canonical references (do not duplicate)

- Service API guide (auth, host normalization, endpoints):  
  `docs_v2/02_Specifications/ORCHESTRATOR_SERVICE_API_INTEGRATION_GUIDE.md`
- Publisher-side mapping + example payload:  
  `docs_v2/08_Epics/001_multi_tenant_orchestrator_runtime_config/022_orchestrator_schema_v2_integration/022_feature.md`  
  `docs_v2/08_Epics/001_multi_tenant_orchestrator_runtime_config/022_orchestrator_schema_v2_integration/stories/02_schema_v2_parsing/022_02_schema-v2-parsing.md`


