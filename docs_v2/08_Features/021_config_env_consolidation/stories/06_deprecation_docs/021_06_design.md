# Deprecation Warnings and Documentation — Story Design

**Feature ID:** 021  
**Story ID:** 021-06  
**Parent Feature:** config_env_consolidation  
**Design Version:** 1.0  
**Date:** 2025-12-23  
**Status:** Design Review  
**Story Definition:** 021_06_deprecation-docs.md  
**Parent Feature Design:** ../../021_design.md

## 1. Summary

### Problem & Context
As the new JSON env vars are adopted, operators using INI-based config need clear guidance to migrate. This story adds deprecation warnings when INI fallback is used and updates documentation with the new `.env` structure.

### Goals
- Emit deprecation warning when INI-based config is used
- Log which specific sections triggered fallback
- Log config source at startup
- Create updated `dotenv.example` with new structure
- Create migration guide documentation

### Non-Goals
- Removing INI file support (maintained for backward compatibility)
- Automated migration scripts (out of scope)
- Changing config behavior

## 2. Context & Assumptions

### Current Behavior
- No deprecation warnings for INI usage
- No logging of config source
- `code_v1/dotenv.example` exists but is for V1

### Constraints
- Must not break existing INI-based deployments
- Warnings should be informative, not alarming
- Documentation must be clear and actionable

### Dependencies
- Stories 01-05: All parsing logic must be complete to know when INI fallback is used

## 3. Requirements

### 3.1 Functional Requirements

**SR1:** Emit deprecation warning when any INI fallback is used:
```
DEPRECATION: Using INI file for [sections]. Migrate to env vars: PUBLISHERS, STORAGE_PATHS, ...
```

**SR2:** Log config source at startup:
- "Config source: env_vars" (all new env vars used)
- "Config source: ini_fallback" (any INI fallback used)

**SR3:** Log which specific INI sections triggered fallback

**SR4:** Create `dotenv.v2.example` with new structure

**SR5:** Add migration section to configuration documentation

### 3.2 Non-Functional Requirements

**NFR1:** Warnings should use standard logging (not stderr)

**NFR2:** Documentation should be clear for non-technical operators

## 4. Architecture & Design (Delta)

### 4.1 Current vs. Proposed

**Current:** No deprecation logging

**Proposed:**
```python
# Track which sources were used
config_sources = {
    "PUBLISHERS": False,
    "EMAIL_SERVER": False,
    "STORAGE_PATHS": False,
    "OPENAI_SETTINGS": False,
    "CAPTIONFILE_SETTINGS": False,
    "CONFIRMATION_SETTINGS": False,
    "CONTENT_SETTINGS": False,
}

# After loading each section, set True if env var was used
# At end, log deprecation if any are False
```

### 4.2 Components & Responsibilities

**`config/loader.py`** (modified):
- Track config source for each section
- Emit deprecation warning at end of `load_application_config()`
- Log config source summary

**`code_v1/dotenv.example`** (updated):
- Add note pointing to new structure

**`dotenv.v2.example`** (new):
- Full new structure with comments

**`docs_v2/05_Configuration/CONFIGURATION.md`** (updated):
- Add migration section

### 4.3 Data & Contracts

**Deprecation log format:**
```python
log_json(
    logger,
    logging.WARNING,
    "config_deprecation",
    message="INI-based config is deprecated. Migrate to JSON env vars.",
    sections=["Content", "Email", "openAI"],  # List of INI sections used
)
```

**Startup log format:**
```python
log_json(
    logger,
    logging.INFO,
    "config_loaded",
    source="env_vars",  # or "ini_fallback"
    publishers_source="PUBLISHERS",  # or "INI"
    storage_source="STORAGE_PATHS",  # or "INI"
)
```

### 4.4 Error Handling & Edge Cases

**Mixed config (some env, some INI):**
- Log each section's source
- Overall source is "ini_fallback" if any INI is used

**All new env vars used:**
- No deprecation warning
- source = "env_vars"

### 4.5 Security, Privacy, Compliance

- No secrets in deprecation logs
- Config values not logged, only sources

## 5. Detailed Flow

### Deprecation Check Flow

```
1. After all config sections loaded:
2. Check config_sources dict
3. ini_sections = [name for name, env_used in config_sources.items() if not env_used]
4. If ini_sections:
   ├─ Log deprecation warning with section names
   └─ overall_source = "ini_fallback"
5. Else:
   └─ overall_source = "env_vars"
6. Log config_loaded with source and per-section sources
```

### Documentation Updates

**dotenv.v2.example:**
```bash
# ============================================================
# Publisher V2 — Environment Configuration (Feature 021)
# ============================================================
# 
# This file shows the consolidated configuration structure.
# Copy to .env and fill in your values.
#
# See: docs_v2/05_Configuration/CONFIGURATION.md

# ==== Secrets (flat, auditable, rotatable) ====
OPENAI_API_KEY=sk-...
DROPBOX_APP_KEY=...
DROPBOX_APP_SECRET=...
DROPBOX_REFRESH_TOKEN=...

# Publisher secrets (only set those you use)
TELEGRAM_BOT_TOKEN=...
EMAIL_PASSWORD=...
# INSTA_PASSWORD=...

# ==== Storage Paths ====
STORAGE_PATHS='{"root": "/Photos/2025", "archive": "/Photos/2025/archive", "keep": "/Photos/2025/approve", "remove": "/Photos/2025/reject"}'

# ==== Publishers ====
PUBLISHERS='[{"type": "telegram", "channel_id": "-100..."}, {"type": "fetlife", "recipient": "...@upload.fetlife.com", "caption_target": "subject", "subject_mode": "normal"}]'

# ==== Email Server (for FetLife publisher) ====
EMAIL_SERVER='{"smtp_server": "smtp.gmail.com", "smtp_port": 587, "sender": "you@gmail.com"}'

# ==== OpenAI Settings (optional, has defaults) ====
# OPENAI_SETTINGS='{"vision_model": "gpt-4o", "caption_model": "gpt-4o-mini"}'

# ==== Other Settings (optional) ====
# CAPTIONFILE_SETTINGS='{"extended_metadata_enabled": true, "artist_alias": "..."}'
# CONFIRMATION_SETTINGS='{"confirmation_to_sender": true, "confirmation_tags_count": 5}'
# CONTENT_SETTINGS='{"hashtag_string": "", "archive": true, "debug": false}'
```

## 6. Testing Strategy

### Unit Tests

| Test Case | Input | Expected |
|-----------|-------|----------|
| All env vars used | All JSON env vars set | No deprecation warning, source="env_vars" |
| All INI fallback | No JSON env vars | Deprecation warning, source="ini_fallback" |
| Mixed sources | Some env, some INI | Deprecation warning lists INI sections |
| Specific section | Only PUBLISHERS missing | Warning mentions publishers config |

### Test File
`publisher_v2/tests/config/test_loader_deprecation.py`

### Documentation Review
- Review `dotenv.v2.example` for completeness
- Review migration guide for clarity

## 7. Risks & Alternatives

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Warning fatigue | Medium | Low | Warning is concise and actionable |
| Operators miss migration | Low | Medium | Deprecation logged every startup |

### Alternatives Considered

1. **No deprecation warning**: Rejected; operators need migration guidance
2. **Strict deprecation (error)**: Rejected; breaks existing deployments

## 8. Work Plan

### Tasks

1. Add config source tracking to `load_application_config()`
2. Add deprecation warning emission
3. Add startup config source log
4. Create `dotenv.v2.example`
5. Update `code_v1/dotenv.example` with pointer to new structure
6. Add migration section to `docs_v2/05_Configuration/CONFIGURATION.md`
7. Write unit tests for deprecation logic

### Definition of Done

- [ ] Deprecation warning emitted when INI used
- [ ] Config source logged at startup
- [ ] `dotenv.v2.example` created with full structure
- [ ] Migration guide added to documentation
- [ ] Unit tests verify deprecation logic
- [ ] No breaking changes to existing deployments

