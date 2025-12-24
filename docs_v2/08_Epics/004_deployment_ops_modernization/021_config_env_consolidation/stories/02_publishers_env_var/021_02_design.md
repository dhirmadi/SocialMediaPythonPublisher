# Publishers Environment Variable — Story Design

**Feature ID:** 021  
**Story ID:** 021-02  
**Parent Feature:** config_env_consolidation  
**Design Version:** 1.0  
**Date:** 2025-12-23  
**Status:** Design Review  
**Story Definition:** 021_02_publishers-env-var.md  
**Parent Feature Design:** ../../021_design.md

## 1. Summary

### Problem & Context
Publisher configuration is currently spread across INI toggle flags (`telegram = true`, `fetlife = true`) and separate sections. This story consolidates publishers into a single `PUBLISHERS` JSON array, where presence in the array implies the publisher is enabled.

### Goals
- Parse `PUBLISHERS` JSON array from environment
- Create appropriate config objects for each publisher type
- Derive `PlatformsConfig` enabled flags from array presence
- Implement precedence: `PUBLISHERS` > INI toggles
- Resolve secrets from flat env vars (not embedded in JSON)

### Non-Goals
- Parsing `EMAIL_SERVER` for SMTP config (Story 03)
- Storage paths (Story 04)
- Deprecation warnings (Story 06)

## 2. Context & Assumptions

### Current Behavior
`loader.py` lines 151-182:
```python
platforms = PlatformsConfig(
    telegram_enabled=cp.getboolean("Content", "telegram", fallback=False),
    instagram_enabled=cp.getboolean("Content", "instagram", fallback=False),
    email_enabled=cp.getboolean("Content", "fetlife", fallback=False),
)
# Then conditionally creates TelegramConfig, InstagramConfig, EmailConfig
```

### Constraints
- Secrets must come from flat env vars (`TELEGRAM_BOT_TOKEN`, `EMAIL_PASSWORD`, `INSTA_PASSWORD`)
- Must fall back to INI if `PUBLISHERS` is not set
- Duplicate publisher types are not allowed (fail fast)

### Dependencies
- Story 01: `_parse_json_env()` helper
- Story 03: `EMAIL_SERVER` for EmailConfig SMTP settings (consumed at runtime)

## 3. Requirements

### 3.1 Functional Requirements

**SR1:** Parse `PUBLISHERS` env var as JSON array of publisher entries

**SR2:** For `type: "telegram"` entries:
- Extract `channel_id` from JSON
- Get `bot_token` from `TELEGRAM_BOT_TOKEN` env var
- Create `TelegramConfig`
- Set `platforms.telegram_enabled = True`

**SR3:** For `type: "fetlife"` entries:
- Extract `recipient`, `caption_target`, `subject_mode` from JSON
- Get SMTP settings from `EMAIL_SERVER` (Story 03) or fallback
- Get password from `EMAIL_PASSWORD` env var
- Create `EmailConfig`
- Set `platforms.email_enabled = True`

**SR4:** For `type: "instagram"` entries:
- Extract `username` from JSON
- Get password from `INSTA_PASSWORD` env var
- Create `InstagramConfig`
- Set `platforms.instagram_enabled = True`

**SR5:** If `PUBLISHERS` contains duplicate types, raise `ConfigurationError`

**SR6:** If `PUBLISHERS` is not set, fall back to INI-based toggles

**SR7:** Unknown publisher types are skipped with a warning log

### 3.2 Non-Functional Requirements

**NFR1:** Secrets (`bot_token`, `password`) never appear in logs

**NFR2:** Publisher order in array doesn't affect behavior

## 4. Architecture & Design (Delta)

### 4.1 Current vs. Proposed

**Current:**
```python
platforms = PlatformsConfig(
    telegram_enabled=cp.getboolean("Content", "telegram", fallback=False),
    ...
)
if platforms.telegram_enabled:
    telegram = TelegramConfig(
        bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        channel_id=os.environ["TELEGRAM_CHANNEL_ID"],
    )
```

**Proposed:**
```python
# Try PUBLISHERS env var first
publishers_json = _parse_json_env("PUBLISHERS")
if publishers_json is not None:
    telegram, instagram, email, platforms = _load_publishers_from_env(publishers_json)
else:
    # Fall back to INI-based loading (existing code)
    ...
```

### 4.2 Components & Responsibilities

**`config/loader.py`** (modified):
- Add `_load_publishers_from_env(entries: list) -> tuple[TelegramConfig | None, InstagramConfig | None, EmailConfig | None, PlatformsConfig]`
- Update `load_application_config()` to try PUBLISHERS first

### 4.3 Data & Contracts

**PUBLISHERS JSON Schema** (from feature design):
```json
[
  {"type": "telegram", "channel_id": "-100123"},
  {"type": "fetlife", "recipient": "...", "caption_target": "subject", "subject_mode": "normal"},
  {"type": "instagram", "username": "..."}
]
```

**Secrets Resolution:**
| Publisher Type | Secret Source |
|----------------|---------------|
| telegram | `TELEGRAM_BOT_TOKEN` env var |
| fetlife | `EMAIL_PASSWORD` env var |
| instagram | `INSTA_PASSWORD` env var |

### 4.4 Error Handling & Edge Cases

**Duplicate types:**
```python
seen_types = set()
for entry in entries:
    if entry["type"] in seen_types:
        raise ConfigurationError(
            f"Duplicate publisher type '{entry['type']}' in PUBLISHERS"
        )
    seen_types.add(entry["type"])
```

**Missing required secret:**
```python
if entry["type"] == "telegram":
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        raise ConfigurationError(
            "TELEGRAM_BOT_TOKEN required when telegram publisher is configured"
        )
```

**Unknown type:**
```python
else:
    logger.warning(f"Unknown publisher type '{entry['type']}' - skipping")
```

### 4.5 Security, Privacy, Compliance

- Secrets never embedded in PUBLISHERS JSON
- Secrets resolved from flat env vars at config load time
- Use `_safe_log_config` when logging publisher config

## 5. Detailed Flow

### `_load_publishers_from_env` Flow

```
1. Validate no duplicate types
2. Initialize: telegram=None, instagram=None, email=None
3. Initialize enabled flags: telegram_enabled=False, instagram_enabled=False, email_enabled=False
4. For each entry in PUBLISHERS:
   ├─ type == "telegram":
   │   ├─ Get TELEGRAM_BOT_TOKEN (required)
   │   ├─ Create TelegramConfig(bot_token, channel_id)
   │   └─ telegram_enabled = True
   ├─ type == "fetlife":
   │   ├─ Get EMAIL_PASSWORD (required)
   │   ├─ Get EMAIL_SERVER settings (Story 03) or use defaults/INI
   │   ├─ Create EmailConfig(sender, recipient, password, smtp_*, caption_target, subject_mode)
   │   └─ email_enabled = True
   ├─ type == "instagram":
   │   ├─ Get INSTA_PASSWORD (required)
   │   ├─ Create InstagramConfig(username, password, session_file)
   │   └─ instagram_enabled = True
   └─ else: log warning, skip
5. Create PlatformsConfig(telegram_enabled, instagram_enabled, email_enabled)
6. Return (telegram, instagram, email, platforms)
```

### Integration with `load_application_config`

```
1. load_dotenv()
2. Parse INI file (still needed for fallback and other sections)
3. Try PUBLISHERS env var:
   ├─ If present: use _load_publishers_from_env()
   └─ If not: use existing INI-based logic
4. Continue with rest of config loading
```

## 6. Testing Strategy

### Unit Tests

| Test Case | Input | Expected |
|-----------|-------|----------|
| Telegram only | `[{"type": "telegram", "channel_id": "-100"}]` + `TELEGRAM_BOT_TOKEN=x` | TelegramConfig created, telegram_enabled=True |
| FetLife only | `[{"type": "fetlife", "recipient": "x@y.com", ...}]` + `EMAIL_PASSWORD=x` | EmailConfig created, email_enabled=True |
| Instagram only | `[{"type": "instagram", "username": "user"}]` + `INSTA_PASSWORD=x` | InstagramConfig created, instagram_enabled=True |
| Multiple publishers | Both telegram and fetlife entries | Both configs created |
| Empty array | `[]` | No configs, all enabled=False |
| Duplicate type | Two telegram entries | ConfigurationError |
| Missing token | Telegram entry, no TELEGRAM_BOT_TOKEN | ConfigurationError |
| Unknown type | `[{"type": "unknown"}]` | Warning logged, skipped |
| Fallback to INI | PUBLISHERS not set | Uses INI toggles |

### Test File
`publisher_v2/tests/config/test_loader_publishers.py`

## 7. Risks & Alternatives

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Email settings not ready (Story 03) | Low | Medium | Can stub EMAIL_SERVER or use defaults |
| Complex conditional logic | Medium | Medium | Clear separation of concerns |

### Alternatives Considered

1. **Parse publishers in separate module**: Adds complexity; inline is simpler
2. **Allow duplicate types**: Rejected per feature spec

## 8. Work Plan

### Tasks

1. Add `_load_publishers_from_env()` function to `loader.py`
2. Add duplicate type validation
3. Update `load_application_config()` to try PUBLISHERS first
4. Handle EmailConfig creation (may need stub for EMAIL_SERVER until Story 03)
5. Write unit tests for all scenarios
6. Add logging for publisher config source

### Definition of Done

- [ ] `PUBLISHERS` env var parsed correctly for all publisher types
- [ ] Secrets resolved from flat env vars (not JSON)
- [ ] Duplicate types rejected with clear error
- [ ] Unknown types logged and skipped
- [ ] Fallback to INI when PUBLISHERS not set
- [ ] Unit tests cover all edge cases
- [ ] No secrets in logs

