# OpenAI and Metadata Settings — Story Design

**Feature ID:** 021  
**Story ID:** 021-05  
**Parent Feature:** config_env_consolidation  
**Design Version:** 1.0  
**Date:** 2025-12-23  
**Status:** Design Review  
**Story Definition:** 021_05_openai-metadata-settings.md  
**Parent Feature Design:** ../../021_design.md

## 1. Summary

### Problem & Context
AI settings, caption file metadata, confirmation email settings, and content settings are currently in separate INI sections. This story consolidates them into JSON env vars: `OPENAI_SETTINGS`, `CAPTIONFILE_SETTINGS`, `CONFIRMATION_SETTINGS`, and `CONTENT_SETTINGS`.

### Goals
- Parse `OPENAI_SETTINGS` for AI model configuration
- Parse `CAPTIONFILE_SETTINGS` for caption file metadata options
- Parse `CONFIRMATION_SETTINGS` for confirmation email behavior
- Parse `CONTENT_SETTINGS` for hashtags, archive, debug flags
- `OPENAI_API_KEY` remains a flat secret env var
- Implement precedence: JSON env vars > INI sections

### Non-Goals
- Changing AI service behavior
- Caption file format changes
- Changing how these settings are used at runtime

## 2. Context & Assumptions

### Current Behavior
`loader.py` lines 111-150 and 183-192:
```python
openai_cfg = OpenAIConfig(
    api_key=os.environ["OPENAI_API_KEY"],
    vision_model=vision_model,  # from INI
    caption_model=caption_model,  # from INI
    system_prompt=cp.get("openAI", "system_prompt", fallback=...),
    ...
)
captionfile = CaptionFileConfig(
    extended_metadata_enabled=cp.getboolean(...),
    artist_alias=cp.get(...),
)
content = ContentConfig(
    hashtag_string=cp.get("Content", "hashtag_string", fallback=""),
    archive=cp.getboolean("Content", "archive", fallback=True),
    debug=cp.getboolean("Content", "debug", fallback=False),
)
```

### Constraints
- `OPENAI_API_KEY` must remain a flat env var (security)
- All fields have sensible defaults
- Must fall back to INI if JSON env vars not set

### Dependencies
- Story 01: `_parse_json_env()` helper
- Story 02/03: CONFIRMATION_SETTINGS applies to EmailConfig fields

## 3. Requirements

### 3.1 Functional Requirements

**SR1:** Parse `OPENAI_SETTINGS` JSON with fields:
- `vision_model` (default: "gpt-4o")
- `caption_model` (default: "gpt-4o-mini")
- `system_prompt`, `role_prompt`
- `sd_caption_enabled`, `sd_caption_single_call_enabled` (defaults: true)
- `sd_caption_model`, `sd_caption_system_prompt`, `sd_caption_role_prompt` (optional)

**SR2:** Parse `CAPTIONFILE_SETTINGS` JSON with fields:
- `extended_metadata_enabled` (default: false)
- `artist_alias` (optional/nullable)

**SR3:** Parse `CONFIRMATION_SETTINGS` JSON with fields:
- `confirmation_to_sender` (default: true)
- `confirmation_tags_count` (default: 5)
- `confirmation_tags_nature` (optional)

**SR4:** Parse `CONTENT_SETTINGS` JSON with fields:
- `hashtag_string` (default: "")
- `archive` (default: true)
- `debug` (default: false)

**SR5:** Precedence: JSON env vars > INI sections

### 3.2 Non-Functional Requirements

**NFR1:** `OPENAI_API_KEY` never appears in JSON or logs

**NFR2:** Partial JSON objects work (missing fields use defaults)

## 4. Architecture & Design (Delta)

### 4.1 Current vs. Proposed

**Current:**
```python
vision_model = cp.get("openAI", "vision_model", fallback=None)
```

**Proposed:**
```python
openai_settings = _load_openai_settings_from_env()
if openai_settings:
    vision_model = openai_settings.get("vision_model", "gpt-4o")
else:
    vision_model = cp.get("openAI", "vision_model", fallback="gpt-4o")
```

### 4.2 Components & Responsibilities

**`config/loader.py`** (modified):
- Add `_load_openai_settings_from_env() -> Optional[dict]`
- Add `_load_captionfile_settings_from_env() -> Optional[dict]`
- Add `_load_confirmation_settings_from_env() -> Optional[dict]`
- Add `_load_content_settings_from_env() -> Optional[dict]`
- Update `load_application_config()` to try JSON first

### 4.3 Data & Contracts

**OPENAI_SETTINGS:**
```json
{
  "vision_model": "gpt-4o",
  "caption_model": "gpt-4o-mini",
  "system_prompt": "...",
  "role_prompt": "...",
  "sd_caption_enabled": true,
  "sd_caption_single_call_enabled": true
}
```

**CAPTIONFILE_SETTINGS:**
```json
{
  "extended_metadata_enabled": true,
  "artist_alias": "Eoel"
}
```

**CONFIRMATION_SETTINGS:**
```json
{
  "confirmation_to_sender": true,
  "confirmation_tags_count": 5,
  "confirmation_tags_nature": "short nouns"
}
```

**CONTENT_SETTINGS:**
```json
{
  "hashtag_string": "#art #photo",
  "archive": true,
  "debug": false
}
```

### 4.4 Error Handling & Edge Cases

**Boolean fields as strings:**
```python
# JSON booleans are native, but validate for safety
if not isinstance(parsed.get("archive", True), bool):
    raise ConfigurationError(
        "CONTENT_SETTINGS.archive must be a boolean"
    )
```

**Invalid model names:** Not validated at config load (runtime will handle)

### 4.5 Security, Privacy, Compliance

- `OPENAI_API_KEY` explicitly NOT in OPENAI_SETTINGS
- No secrets in any of these JSON env vars

## 5. Detailed Flow

### Generic Pattern for Each Setting

```
1. parsed = _parse_json_env("SETTING_NAME")
2. If parsed is None:
   └─ Return None (use INI fallback)
3. Apply defaults for missing fields
4. Validate types for critical fields (booleans, integers)
5. Return dict with all fields
```

### Integration with Config Loading

```python
# OPENAI_SETTINGS
openai_json = _load_openai_settings_from_env()
if openai_json:
    vision_model = openai_json.get("vision_model", "gpt-4o")
    # ... etc
else:
    # Use existing INI logic

# CAPTIONFILE_SETTINGS
captionfile_json = _load_captionfile_settings_from_env()
if captionfile_json:
    extended_metadata = captionfile_json.get("extended_metadata_enabled", False)
else:
    extended_metadata = cp.getboolean("CaptionFile", "extended_metadata_enabled", fallback=False)

# CONFIRMATION_SETTINGS
confirmation_json = _load_confirmation_settings_from_env()
# Applied to EmailConfig if email publisher is enabled

# CONTENT_SETTINGS
content_json = _load_content_settings_from_env()
if content_json:
    content = ContentConfig(
        hashtag_string=content_json.get("hashtag_string", ""),
        archive=content_json.get("archive", True),
        debug=content_json.get("debug", False),
    )
```

## 6. Testing Strategy

### Unit Tests

| Test Case | Setting | Input | Expected |
|-----------|---------|-------|----------|
| Full config | OPENAI | All fields | Uses all values |
| Minimal config | OPENAI | `{}` | Uses all defaults |
| Partial config | CAPTIONFILE | `{"extended_metadata_enabled": true}` | artist_alias=None |
| Not set | CONTENT | None | Returns None |
| Invalid bool | CONTENT | `{"archive": "yes"}` | ConfigurationError |
| Integer field | CONFIRMATION | `{"confirmation_tags_count": 10}` | count=10 |

### Test File
`publisher_v2/tests/config/test_loader_settings.py`

## 7. Risks & Alternatives

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Many similar loader functions | Medium | Low | Consistent pattern makes maintenance easy |
| Prompt strings with special chars | Low | Low | JSON handles escaping |

### Alternatives Considered

1. **Single mega SETTINGS env var**: Rejected; harder to partially override
2. **Validate model names**: Rejected; runtime validation is sufficient

## 8. Work Plan

### Tasks

1. Add `_load_openai_settings_from_env()` function
2. Add `_load_captionfile_settings_from_env()` function
3. Add `_load_confirmation_settings_from_env()` function
4. Add `_load_content_settings_from_env()` function
5. Update OpenAIConfig creation to use OPENAI_SETTINGS
6. Update CaptionFileConfig creation to use CAPTIONFILE_SETTINGS
7. Update EmailConfig confirmation fields to use CONFIRMATION_SETTINGS
8. Update ContentConfig creation to use CONTENT_SETTINGS
9. Write unit tests for all settings

### Definition of Done

- [ ] All four settings parsed correctly
- [ ] Defaults applied for missing fields
- [ ] Type validation for booleans and integers
- [ ] OPENAI_API_KEY remains flat env var
- [ ] Fallback to INI when not set
- [ ] Unit tests cover all scenarios

