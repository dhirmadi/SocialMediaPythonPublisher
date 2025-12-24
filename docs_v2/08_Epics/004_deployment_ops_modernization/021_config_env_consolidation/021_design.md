# Configuration Environment Variable Consolidation — Feature Design

**Feature ID:** 021  
**Design Version:** 1.0  
**Date:** 2025-12-22  
**Status:** Shipped  
**Author:** Platform Team  
**Feature Request:** 021_feature.md

**Implementation Completed:** 2025-12-23  
**Implementation Evidence:** See `021_feature.md` → “Completion (Evidence)” and story summaries under `stories/`.

## 1. Summary

### Problem
Configuration is split between `.env` and `configfiles/*.ini`, creating cognitive overhead, deployment friction, and complexity for the upcoming Orchestrator API migration.

### Goals
- Consolidate configuration into environment variables, but **keep secrets as separate env vars** (auditable + rotatable)
- Use JSON-encoded arrays/objects for **non-secret groupings only** (operationally safer)
- Remove redundant publisher toggle flags (derive enabled state from `PUBLISHERS` array presence)
- Align storage path semantics with Orchestrator API contract
- Maintain backward compatibility with existing INI-based configuration

### Non-Goals
- Implementing Orchestrator API integration (Epic 001)
- Adding new features or publishers
- Changing runtime behavior

## 2. Context & Assumptions

### Current State

**Config Loader** (`publisher_v2/config/loader.py`):
- Loads `.env` via `python-dotenv`
- Parses INI via `configparser`
- Constructs Pydantic models: `ApplicationConfig`, `DropboxConfig`, `EmailConfig`, etc.

**Current Split**:
| Setting | Current Location | New Location |
|---------|-----------------|--------------|
| `DROPBOX_APP_KEY`, `DROPBOX_REFRESH_TOKEN` | .env | .env (unchanged) |
| `image_folder`, `archive`, `folder_keep`, `folder_remove` | INI [Dropbox] | `STORAGE_PATHS` JSON |
| `telegram = true/false` | INI [Content] | Removed (implicit from `PUBLISHERS`) |
| `TELEGRAM_BOT_TOKEN` | .env | .env (flat secret, unchanged) |
| `TELEGRAM_CHANNEL_ID` | .env | `PUBLISHERS` JSON array (non-secret) |
| `fetlife = true/false` | INI [Content] | Removed (implicit from `PUBLISHERS`) |
| `sender`, `recipient`, `smtp_server`, `smtp_port` | INI [Email] + .env | `EMAIL_SERVER` + `PUBLISHERS` JSON |
| `EMAIL_PASSWORD` | .env | .env (flat secret, unchanged) |
| `caption_target`, `subject_mode` | INI [Email] | `PUBLISHERS` (FetLife entry) |
| `vision_model`, `caption_model`, prompts | INI [openAI] | `OPENAI_SETTINGS` JSON |
| `confirmation_*` | INI [Hashtags]/[Email] | `CONFIRMATION_SETTINGS` JSON |
| `extended_metadata_enabled`, `artist_alias` | INI [CaptionFile] | `CAPTIONFILE_SETTINGS` JSON |
| `hashtag_string`, `archive`, `debug` | INI [Content] | `CONTENT_SETTINGS` JSON |

### Constraints
- Environment variables must be valid shell strings (JSON escaping required for multiline)
- Pydantic models remain unchanged; only the loader adapts
- Backward compatibility required during transition period
 - Secrets must remain flat env vars (e.g., `EMAIL_PASSWORD`, `TELEGRAM_BOT_TOKEN`) and must not be embedded in JSON blobs

### Dependencies
- `python-dotenv` (existing)
- `json` (stdlib)
- Orchestrator API contract alignment (future)

## 3. Requirements

### 3.1 Functional Requirements

**FR1**: Parse `PUBLISHERS` JSON array and create corresponding publisher configurations.

**FR2**: Parse `EMAIL_SERVER` JSON object for shared email infrastructure settings.

**FR3**: Parse `STORAGE_PATHS` JSON object with absolute paths matching Orchestrator API contract.

**FR4**: Parse `OPENAI_SETTINGS` JSON object for AI model and prompt configuration.

**FR5**: Parse `CAPTIONFILE_SETTINGS` JSON object for caption file metadata options.

**FR6**: Parse `CONFIRMATION_SETTINGS` JSON object for confirmation email behavior.

**FR7**: Implement precedence: New JSON env vars > Old individual env vars > INI file.

**FR8**: Emit deprecation warning when falling back to INI-based configuration.

**FR9**: Fail fast with clear error messages on JSON parse errors.

### 3.2 Non-Functional Requirements

**NFR1**: Startup time must not regress (JSON parsing is O(1) for reasonable sizes).

**NFR2**: Secrets in JSON (passwords, tokens) must never appear in logs.
**NFR2b**: Secrets must not be embedded in JSON env var blobs (avoid audit/rotation complexity).

**NFR3**: Config loader must remain synchronous (no async changes).

## 4. Architecture & Design

### 4.1 Proposed Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        Environment                                │
│  PUBLISHERS, EMAIL_SERVER, STORAGE_PATHS, OPENAI_SETTINGS, ...  │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                   config/loader.py                                │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │  _parse_json_env(var_name) -> Optional[dict/list]       │     │
│  │  _load_publishers_from_env() -> List[PublisherEntry]    │     │
│  │  _load_email_server_from_env() -> Optional[EmailServer] │     │
│  │  _load_storage_paths_from_env() -> Optional[StoragePaths]│    │
│  │  _load_openai_from_env() -> Optional[OpenAISettings]    │     │
│  │  ...                                                     │     │
│  └─────────────────────────────────────────────────────────┘     │
│                              │                                    │
│                              ▼                                    │
│  ┌─────────────────────────────────────────────────────────┐     │
│  │  load_application_config()                               │     │
│  │    1. Try new JSON env vars                              │     │
│  │    2. Fall back to old env vars                          │     │
│  │    3. Fall back to INI file                              │     │
│  │    4. Emit deprecation warning if INI used               │     │
│  └─────────────────────────────────────────────────────────┘     │
└─────────────────────────────┬────────────────────────────────────┘
                              │
                              ▼
┌──────────────────────────────────────────────────────────────────┐
│                  config/schema.py (unchanged)                     │
│  ApplicationConfig, DropboxConfig, EmailConfig, TelegramConfig  │
└──────────────────────────────────────────────────────────────────┘
```

### 4.2 Components & Responsibilities

**`config/loader.py`** (modified):
- New helper functions for JSON parsing
- New loading functions for each JSON env var
- Updated `load_application_config()` with precedence logic
- Deprecation warning emission

**`config/schema.py`** (unchanged):
- Pydantic models remain stable
- No schema changes required

**`config/env_parsers.py`** (new, optional):
- If complexity grows, extract JSON parsing to dedicated module
- For now, inline in loader.py is acceptable

### 4.3 Data Model / Schemas

#### PUBLISHERS JSON Schema

```json
{
  "type": "array",
  "items": {
    "oneOf": [
      {
        "type": "object",
        "properties": {
          "type": { "const": "telegram" },
          "channel_id": { "type": "string" }
        },
        "required": ["type", "channel_id"]
      },
      {
        "type": "object",
        "properties": {
          "type": { "const": "fetlife" },
          "recipient": { "type": "string" },
          "caption_target": { "enum": ["subject", "body", "both"], "default": "subject" },
          "subject_mode": { "enum": ["normal", "private", "avatar"], "default": "normal" }
        },
        "required": ["type", "recipient"]
      },
      {
        "type": "object",
        "properties": {
          "type": { "const": "instagram" },
          "username": { "type": "string" }
        },
        "required": ["type", "username"]
      }
    ]
  }
}
```

#### EMAIL_SERVER JSON Schema

```json
{
  "type": "object",
  "properties": {
    "smtp_server": { "type": "string", "default": "smtp.gmail.com" },
    "smtp_port": { "type": "integer", "default": 587 },
    "sender": { "type": "string" }
  },
  "required": ["sender"]
}
```

#### STORAGE_PATHS JSON Schema

```json
{
  "type": "object",
  "properties": {
    "root": { "type": "string", "description": "Absolute path to image folder" },
    "archive": { "type": "string", "description": "Absolute path to archive folder" },
    "keep": { "type": "string", "description": "Absolute path to keep/approve folder" },
    "remove": { "type": "string", "description": "Absolute path to remove/reject folder" }
  },
  "required": ["root"]
}
```

**Path handling logic**:
- If `archive`, `keep`, `remove` are absolute paths (start with `/`), use as-is
- Absolute paths must not contain `..` path components.
- If relative, join with `root` (backward compatibility with current INI behavior)
- Orchestrator API always provides absolute paths, so new deployments use absolute

#### OPENAI_SETTINGS JSON Schema

```json
{
  "type": "object",
  "properties": {
    "vision_model": { "type": "string", "default": "gpt-4o" },
    "caption_model": { "type": "string", "default": "gpt-4o-mini" },
    "system_prompt": { "type": "string" },
    "role_prompt": { "type": "string" },
    "sd_caption_enabled": { "type": "boolean", "default": true },
    "sd_caption_single_call_enabled": { "type": "boolean", "default": true }
  }
}
```

#### CAPTIONFILE_SETTINGS JSON Schema

```json
{
  "type": "object",
  "properties": {
    "extended_metadata_enabled": { "type": "boolean", "default": false },
    "artist_alias": { "type": "string", "nullable": true }
  }
}
```

#### CONFIRMATION_SETTINGS JSON Schema

```json
{
  "type": "object",
  "properties": {
    "confirmation_to_sender": { "type": "boolean", "default": true },
    "confirmation_tags_count": { "type": "integer", "default": 5 },
    "confirmation_tags_nature": { "type": "string" }
  }
}
```

#### CONTENT_SETTINGS JSON Schema (parity with current INI [Content])

```json
{
  "type": "object",
  "properties": {
    "hashtag_string": { "type": "string", "default": "" },
    "archive": { "type": "boolean", "default": true },
    "debug": { "type": "boolean", "default": false }
  }
}
```

### 4.4 API/Contracts

No external API changes. Internal loader contract:

```python
def load_application_config(
    config_file_path: str,
    env_path: str | None = None
) -> ApplicationConfig:
    """
    Load configuration with precedence:
    1. New JSON env vars (PUBLISHERS, EMAIL_SERVER, etc.)
    2. Old individual env vars (SMTP_SERVER, EMAIL_PASSWORD, etc.)
    3. INI file sections
    
    Emits deprecation warning if INI fallback is used.
    """
```

### 4.5 Error Handling & Retries

**JSON Parse Errors**:
```python
def _parse_json_env(var_name: str) -> Optional[dict | list]:
    value = os.environ.get(var_name)
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Invalid JSON in {var_name}: {exc.msg} at position {exc.pos}"
        ) from exc
```

**Validation approach update (recommended):**
- Prefer Pydantic `TypeAdapter.validate_json(...)` for JSON env vars so errors include **field context**, not just character position.

**Missing Required Fields**:
- Pydantic validation catches missing fields
- Error message includes field name and expected type

### 4.6 Security, Privacy, Compliance

**Secret Handling**:
- Secrets remain in flat env vars:
  - Telegram: `TELEGRAM_BOT_TOKEN`
  - Email: `EMAIL_PASSWORD`
  - Instagram: `INSTA_PASSWORD`
- JSON env vars must not embed secrets (reduces rotation/audit risk).
- Logging must never print secret env values.

```python
def _safe_log_config(cfg: dict, redact_keys: set[str]) -> dict:
    """Return config dict with sensitive values redacted for logging."""
    return {
        k: "***REDACTED***" if k in redact_keys else v
        for k, v in cfg.items()
    }
```

**No New Attack Surface**:
- JSON parsing is safe (no eval, no code execution)
- Same trust model as current INI parsing

## 5. Detailed Flow

### Config Loading Sequence

```
1. load_application_config(config_file_path, env_path)
   │
   ├─ load_dotenv(env_path)
   │
   ├─ Try STORAGE_PATHS env var
   │   ├─ If present: parse JSON → DropboxConfig paths
   │   └─ Else: fall back to INI [Dropbox] section
   │
   ├─ Try OPENAI_SETTINGS env var
   │   ├─ If present: parse JSON → OpenAIConfig
   │   └─ Else: fall back to INI [openAI] section
   │
   ├─ Try PUBLISHERS env var
   │   ├─ If present: parse JSON array
   │   │   ├─ For each entry with type="telegram": create TelegramConfig
   │   │   ├─ For each entry with type="fetlife": create EmailConfig
   │   │   └─ For each entry with type="instagram": create InstagramConfig
   │   └─ Else: fall back to INI [Content] toggles + sections
   │
   ├─ Try EMAIL_SERVER env var
   │   ├─ If present: parse JSON → use for EmailConfig smtp_*/sender/password
   │   └─ Else: fall back to INI [Email] + SMTP_* env vars
   │
   ├─ Try CONFIRMATION_SETTINGS env var
   │   ├─ If present: parse JSON → EmailConfig confirmation_* fields
   │   └─ Else: fall back to INI [Hashtags]/[Email] section
   │
   ├─ Try CAPTIONFILE_SETTINGS env var
   │   ├─ If present: parse JSON → CaptionFileConfig
   │   └─ Else: fall back to INI [CaptionFile] section
   │
   ├─ If any INI fallback was used:
   │   └─ log.warning("Deprecation: INI config detected. Migrate to env vars.")
   │
   └─ Return ApplicationConfig(...)
```

### Publisher Type Mapping

| PUBLISHERS[].type | Internal Config | Publisher Class |
|-------------------|-----------------|-----------------|
| `telegram` | `TelegramConfig` | `TelegramPublisher` |
| `fetlife` | `EmailConfig` | `EmailPublisher` |
| `instagram` | `InstagramConfig` | `InstagramPublisher` |

### Edge Cases

1. **Empty PUBLISHERS array**: No publishers enabled (valid configuration for preview-only mode)
2. **Multiple publishers of same type**: Explicitly invalid; fail fast with clear error (no “undefined behavior”)
3. **Unknown publisher type**: Skip with warning log (forward compatibility)
4. **STORAGE_PATHS with relative paths**: Join with root for backward compatibility

**Secrets resolution convention (Feature 021 policy):**
- Telegram publisher uses `TELEGRAM_BOT_TOKEN` from env + `channel_id` from PUBLISHERS entry.
- Email/FetLife publisher uses `EMAIL_PASSWORD` from env + sender/smtp from EMAIL_SERVER + recipient from PUBLISHERS entry.
- Instagram publisher uses `INSTA_PASSWORD` from env + username from PUBLISHERS entry.

## 6. Rollout & Ops

### Feature Flags
- No feature flag needed; backward compatibility handles transition

### Configuration Migration Guide

**Before** (INI + .env):
```ini
# configfiles/fetlife.ini
[Dropbox]
image_folder = /Photos/Tati/2025
archive = archive
folder_keep = approve
folder_reject = reject

[Content]
telegram = true
fetlife = true
instagram = false

[Email]
sender = user@gmail.com
recipient = 123@upload.fetlife.com
smtp_server = smtp.gmail.com
smtp_port = 587
caption_target = subject
subject_mode = normal

[openAI]
vision_model = gpt-4o
caption_model = gpt-4o-mini
system_prompt = ...
role_prompt = ...

[CaptionFile]
extended_metadata_enabled = true
artist_alias = Eoel
```

```bash
# .env
EMAIL_PASSWORD=secret
TELEGRAM_BOT_TOKEN=123:abc
TELEGRAM_CHANNEL_ID=-100123
```

**After** (.env only):
```bash
# .env
OPENAI_API_KEY=sk-...
DROPBOX_APP_KEY=...
DROPBOX_APP_SECRET=...
DROPBOX_REFRESH_TOKEN=...

STORAGE_PATHS='{"root": "/Photos/Tati/2025", "archive": "/Photos/Tati/2025/archive", "keep": "/Photos/Tati/2025/approve", "remove": "/Photos/Tati/2025/reject"}'

TELEGRAM_BOT_TOKEN=123:abc
EMAIL_PASSWORD=secret
INSTA_PASSWORD=secret

PUBLISHERS='[{"type": "telegram", "channel_id": "-100123"}, {"type": "fetlife", "recipient": "123@upload.fetlife.com", "caption_target": "subject", "subject_mode": "normal"}]'

EMAIL_SERVER='{"smtp_server": "smtp.gmail.com", "smtp_port": 587, "sender": "user@gmail.com"}'

OPENAI_SETTINGS='{"vision_model": "gpt-4o", "caption_model": "gpt-4o-mini", "system_prompt": "...", "role_prompt": "..."}'

CAPTIONFILE_SETTINGS='{"extended_metadata_enabled": true, "artist_alias": "Eoel"}'

CONFIRMATION_SETTINGS='{"confirmation_to_sender": true, "confirmation_tags_count": 5, "confirmation_tags_nature": "short, lowercase, human-friendly topical nouns; no hashtags; no emojis"}'

CONTENT_SETTINGS='{"hashtag_string": "#art #photography", "archive": true, "debug": false}'
```

### Monitoring
- Log config source at startup: "Config loaded from: env_vars" or "Config loaded from: ini_fallback"
- Deprecation warnings should be visible in logs

## 7. Testing Strategy

### Unit Tests

| Test Case | Input | Expected |
|-----------|-------|----------|
| Parse valid PUBLISHERS array | JSON with telegram + fetlife | TelegramConfig + EmailConfig created |
| Parse invalid JSON | Malformed JSON | ConfigurationError with position info |
| Empty PUBLISHERS | `[]` | Empty publishers list, no error |
| Precedence: env over INI | Both present | Env var values used |
| Backward compat: INI only | No new env vars | INI values used, deprecation warning |
| Absolute storage paths | `/Photos/archive` | Used as-is |
| Relative storage paths | `archive` | Joined with root |

### Integration Tests

| Scenario | Verification |
|----------|--------------|
| Full workflow with new env vars | Publish succeeds, correct recipients |
| Mixed config (some env, some INI) | Correct precedence applied |
| Web interface with new config | All endpoints functional |

### E2E Tests

- Deploy with new `.env` structure to staging
- Execute full publish workflow
- Verify Dropbox, Telegram, Email publishers work correctly

## 8. Risks & Alternatives

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| JSON escaping issues in shell | Medium | High | Provide example `.env` files |
| Operators miss migration | Low | Medium | Deprecation warnings in logs |
| Path format confusion | Medium | High | Clear docs, validation errors |

### Alternatives Considered

1. **YAML instead of JSON**: Rejected; JSON is sufficient and more common in env vars
2. **Keep INI, add env overrides only**: Rejected; doesn't clean up the split
3. **Single mega JSON env var**: Rejected; harder to manage partial overrides

## 9. Work Plan

### Milestones

| Milestone | Exit Criteria | Target |
|-----------|---------------|--------|
| M1: Design Review | Design approved | Day 1 |
| M2: Core Implementation | Loader updated, tests passing | Day 3 |
| M3: Documentation | Migration guide complete | Day 4 |
| M4: Staging Validation | E2E tests pass on staging | Day 5 |

### Tasks

1. Implement JSON parsing helpers in `loader.py`
2. Update `load_application_config()` with precedence logic
3. Add deprecation warning emission
4. Write unit tests for all parsing paths
5. Update `dotenv.example` with new structure
6. Create migration documentation
7. Test on staging environment

### Definition of Done

- [x] All new JSON env vars parsed correctly
- [x] Precedence order implemented
- [x] Backward compatibility maintained
- [x] Unit tests: 100% coverage of new code
- [x] Integration tests passing
- [x] No secrets in logs
- [x] Documentation updated
- [x] Staging validation complete

## 10. Derived Stories

Based on this design, the following implementation stories are required:

- **Story 01: JSON Config Parser Infrastructure** — Add JSON parsing helpers and error handling to the config loader module.

- **Story 02: Publishers Environment Variable** — Implement `PUBLISHERS` JSON array parsing and publisher instantiation with precedence over INI toggles.

- **Story 03: Email Server Environment Variable** — Implement `EMAIL_SERVER` JSON parsing for shared SMTP configuration.

- **Story 04: Storage Paths Environment Variable** — Implement `STORAGE_PATHS` JSON parsing with absolute/relative path handling.

- **Story 05: OpenAI and Metadata Settings** — Implement `OPENAI_SETTINGS`, `CAPTIONFILE_SETTINGS`, and `CONFIRMATION_SETTINGS` JSON parsing.

- **Story 06: Deprecation Warnings and Documentation** — Add deprecation logging for INI fallback usage and update operator documentation.

- **Story 07: Heroku Pipeline Migration (Stop Using `FETLIFE_INI`)** — Provide a safe rollout plan and concrete Heroku/local migration instructions so all apps in the `fetlife` pipeline can remove `FETLIFE_INI` and run env-first.

