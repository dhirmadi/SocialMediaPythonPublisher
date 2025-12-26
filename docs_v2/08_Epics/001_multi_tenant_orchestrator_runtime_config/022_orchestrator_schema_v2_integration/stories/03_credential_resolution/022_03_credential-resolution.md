# Story 03 — Credential Resolution

**Feature ID:** 022  
**Story ID:** 022-03  
**Status:** Shipped  
**Date:** 2025-12-25

---

## Context / Scope

The orchestrator's `/v1/credentials/resolve` endpoint now supports multiple providers:

- `dropbox` → `{ refresh_token, version }`
- `openai` → `{ api_key, version }`
- `telegram` → `{ bot_token, version }`
- `smtp` → `{ password, version }`

Publisher V2 must resolve credentials when runtime config includes `credentials_ref` or `password_ref` fields, then inject the resolved secrets into downstream clients.

**Agreed behavior** (from issue #25):
- **Critical credentials** (Dropbox/storage): fail fast if resolution fails (503)
- **Optional credentials** (telegram, openai, smtp): degrade gracefully, disable that feature

**Parent feature:** [022_feature.md](../../022_feature.md)  
**Depends on:** Story 01 (Config Source Abstraction), Story 02 (Schema V2 Parsing)

---

## Dependencies

| Story | Requirement |
|-------|-------------|
| 01 — Config Source Abstraction | `OrchestratorConfigSource.get_credentials()` signature defined |
| 02 — Schema V2 Parsing | `credentials_ref` values available from parsed config |

---

## Behaviour

### Preconditions

- Story 02 is implemented (orchestrator config with `credentials_ref` values is available)
- Orchestrator Feature 11 (multi-secret credentials) is deployed

### Main Flow

1. Implement `OrchestratorConfigSource.get_credentials(host, credentials_ref)`:
   - Extract tenant from host using `extract_tenant(host, base_domain)`
   - Call `POST /v1/credentials/resolve`
   - Headers:
     - `Authorization: Bearer <ORCHESTRATOR_SERVICE_TOKEN>`
     - `X-Tenant: <tenant>` (extracted from host)
     - `X-Request-Id: <uuid>`
   - Body: `{ "credentials_ref": "<credentials_ref>" }`

2. Parse response by `provider`:

   | Provider | Response fields | Usage |
   |----------|-----------------|-------|
   | `dropbox` | `refresh_token`, `version` | Dropbox OAuth client |
   | `openai` | `api_key`, `version` | OpenAI client |
   | `telegram` | `bot_token`, `version` | Telegram bot client |
   | `smtp` | `password`, `version` | SMTP authentication |

3. Create typed credential payloads:
   - `DropboxCredentials` — `refresh_token: str`, `version: str`
   - `OpenAICredentials` — `api_key: str`, `version: str`
   - `TelegramCredentials` — `bot_token: str`, `version: str`
   - `SMTPCredentials` — `password: str`, `version: str`

4. Update service initialization to resolve credentials after config load:
   - Storage: resolve `config.storage.credentials_ref` → inject into Dropbox client
   - AI: resolve `config.ai.credentials_ref` → inject into OpenAI client
   - Publishers: resolve `config.publishers[*].credentials_ref` by type (see special handling below)
   - Email: resolve `config.email_server.password_ref` → inject into SMTP client

5. **FetLife publisher special handling**:

   FetLife publishers do NOT have their own `credentials_ref` — they use the shared email server infrastructure:

   ```
   ┌─────────────────────────────────────────────────────────────────┐
   │                        Email Server                              │
   │  (Gmail SMTP authentication - shared infrastructure)             │
   │  • email_server.host (smtp.gmail.com)                           │
   │  • email_server.port (587)                                      │
   │  • email_server.from_email (sender@gmail.com)                   │
   │  • email_server.password_ref → resolve to SMTP password         │
   └─────────────────────────────────┬───────────────────────────────┘
                                     │ authenticates via
                                     ▼
   ┌─────────────────────────────────────────────────────────────────┐
   │                     FetLife Publisher                            │
   │  (sends email TO FetLife's upload address)                      │
   │  • recipient: 123456@upload.fetlife.com                         │
   │  • credentials_ref: null  ← EXPECTED! No FetLife auth needed   │
   └─────────────────────────────────────────────────────────────────┘
   ```

   **Resolution flow:**
   - For `type: telegram` publishers: resolve `publisher.credentials_ref` → `bot_token`
   - For `type: fetlife` publishers: `credentials_ref` will be `null`; use `email_server.password_ref` → SMTP `password`
   - FetLife does not require authentication; the email server does

6. Implement error handling:
   - **Critical (storage)**: 404/403/5xx → raise `CredentialResolutionError` → 503 response
   - **Optional (ai, telegram, smtp)**: 404/403/5xx → log warning, disable feature

### Alternative Flows

- **Env-first mode**: `EnvConfigSource.get_credentials()` returns flat env var values directly
- **No credentials_ref**: If a config block doesn't have a `credentials_ref`, skip resolution (may be optional feature)
- **FetLife with `credentials_ref: null`**: This is expected; FetLife publishers use `email_server.password_ref` for SMTP authentication (not per-publisher credentials)

### Error Flows

- **404**: Credential not found or not authorized for tenant
- **403**: Invalid service token
- **429**: Rate limited (retry with backoff)
- **5xx**: Transient failure (retry with backoff)

### Retry Policy

```python
RETRY_CONFIG = {
    "base_delay_ms": 250,
    "max_delay_ms": 5000,
    "max_attempts": 3,
    "jitter": True,
    "retryable_status": {429, 500, 502, 503, 504},
}
```

### Eager vs Lazy Resolution Strategy

| Credential | Strategy | Rationale |
|------------|----------|-----------|
| `storage` (Dropbox) | **Eager** | Required for all operations; resolve immediately after config load |
| `ai` (OpenAI) | **Lazy** | Only needed if AI features enabled and used |
| `telegram` | **Lazy** | Only needed if Telegram publisher present and publishing |
| `smtp` | **Lazy** | Only needed if email-based publishers present and publishing |

**Implementation:** Storage credentials resolved in `get_config()`. Others resolved on first access via lazy property or explicit `resolve_if_needed()` call.

---

## Acceptance Criteria

- [ ] `OrchestratorConfigSource.get_credentials()` calls `/v1/credentials/resolve` with correct headers
- [ ] Response is parsed into typed credential payloads (`DropboxCredentials`, `OpenAICredentials`, etc.)
- [ ] `provider` field in response is validated against expected type
- [ ] Storage credential resolution failure returns 503 (fail fast)
- [ ] Optional credential resolution failure logs warning and disables feature
- [ ] Resolved credentials are passed to downstream clients (Dropbox, OpenAI, Telegram, SMTP)
- [ ] FetLife publishers with `credentials_ref: null` are handled correctly (use `email_server.password_ref`)
- [ ] SMTP credential resolution failure disables FetLife publisher (not 503)
- [ ] No secrets appear in logs (refresh tokens, API keys, bot tokens, passwords)
- [ ] No `credentials_ref` values appear in logs
- [ ] Unit tests cover all 4 provider types
- [ ] Unit test verifies FetLife uses email_server password
- [ ] Integration test verifies credential injection into clients
- [ ] Retry policy implemented with exponential backoff + jitter
- [ ] Storage credentials resolved eagerly (during config load)
- [ ] AI/telegram/smtp credentials resolved lazily (on first use)

---

## Testing

### Manual Testing

1. Configure tenant with all 4 credential types in orchestrator → verify all resolve successfully
2. Remove telegram credentials from orchestrator → verify Publisher still works (telegram disabled)
3. Remove dropbox credentials → verify Publisher returns 503 for all requests
4. Test with invalid service token → verify 403 handling

### Automated Tests

Add/extend tests under `publisher_v2/tests/config/`:

- `test_credential_resolution.py`:
  - `test_resolve_dropbox_credentials`
  - `test_resolve_openai_credentials`
  - `test_resolve_telegram_credentials`
  - `test_resolve_smtp_credentials`
  - `test_storage_resolution_failure_raises_error`
  - `test_optional_resolution_failure_degrades_gracefully`
  - `test_retry_on_429_and_5xx`
  - `test_no_secrets_in_logs` (capture log output and assert)

---

## Implementation Notes

### Files to Create/Modify

- **Create**: `publisher_v2/src/publisher_v2/config/credentials.py`
  - `DropboxCredentials`, `OpenAICredentials`, `TelegramCredentials`, `SMTPCredentials`
  - `CredentialPayload` union type

- **Modify**: `publisher_v2/src/publisher_v2/config/orchestrator_client.py`
  - Add `resolve_credentials(tenant, credentials_ref)` method

- **Modify**: `publisher_v2/src/publisher_v2/config/source.py`
  - Implement `OrchestratorConfigSource.get_credentials()`

- **Modify**: `publisher_v2/src/publisher_v2/web/service.py`
  - Resolve credentials after config load
  - Inject into service clients

### Credential Resolution Response Shape

```json
{
  "provider": "openai",
  "version": "sha256-hex",
  "api_key": "sk-..."
}
```

Note: Response shape varies by provider (different secret field names).

### Error Handling Matrix

| Scenario | HTTP Status | Publisher Behavior |
|----------|-------------|-------------------|
| Storage cred missing | 404 | 503, no operations (CRITICAL) |
| AI cred missing | 404 | AI features disabled, continue |
| Telegram cred missing | 404 | Telegram publisher disabled |
| SMTP cred missing (`email_server.password_ref`) | 404 | FetLife publisher disabled |
| FetLife `credentials_ref: null` | N/A | Expected — use `email_server.password_ref` instead |
| Invalid token | 403 | 503, log error |
| Rate limited | 429 | Retry with backoff |
| Server error | 5xx | Retry, then 503 if exhausted |

**Note on FetLife:**
- FetLife does NOT require its own credentials
- FetLife sends emails **TO** `<id>@upload.fetlife.com`
- The email is sent **FROM** `email_server.from_email` via SMTP
- SMTP authentication uses the resolved `email_server.password_ref`

### Repo Rules

- **Secrets must never be logged** — Use existing `SanitizingFilter`
- **`credentials_ref` is sensitive-adjacent** — Do not log
- **Async hygiene** — Use `httpx.AsyncClient`

---

## Change History

| Date | Change |
|------|--------|
| 2025-12-24 | Initial story draft |
| 2025-12-25 | Clarified FetLife credential handling (uses email_server.password_ref, not per-publisher credentials) |

