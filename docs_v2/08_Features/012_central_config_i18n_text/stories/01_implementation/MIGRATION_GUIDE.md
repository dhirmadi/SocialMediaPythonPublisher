# Configuration Migration Guide — INI to Static Config

**Feature:** 012 (Centralized Configuration)  
**Date:** 2025-11-22  
**Status:** Recommended Migration

---

## Overview

Several values currently in INI files are better suited for **static configuration** (YAML). This guide explains what should move and why.

---

## Values to Migrate

### 1. Email/FetLife Platform Behavior ✅ MIGRATED

**Previously in INI (`[Email]` section):**
```ini
caption_target = subject
subject_mode = normal
```

**Now in `platform_limits.yaml`:**
```yaml
email:
  max_caption_length: 240
  caption_target: subject  # subject | body | both
  subject_mode: normal     # normal | private | avatar
```

**Why?**
- These are **platform behavior rules**, not deployment-specific settings
- They rarely change per environment
- They're tied to platform constraints (like caption length)
- Versioning them with code makes behavior predictable

**Migration:**
- ✅ Added to `platform_limits.yaml` with defaults
- ⚠️ **INI values still work** (backward compatible)
- 📋 **Recommended:** Remove from INI and rely on static config

---

### 2. Hashtags/Confirmation Settings

**Currently in INI (`[Hashtags]` section):**
```ini
confirmation_to_sender = true
confirmation_tags_count = 5
confirmation_tags_nature = short, lowercase, human-friendly topical nouns as used on FetLife; no hashtags; no emojis
```

**Analysis:**

| Setting | Current Location | Recommended Location | Reason |
|---------|------------------|---------------------|--------|
| `confirmation_to_sender` | INI | **INI (keep)** | Deployment-specific toggle |
| `confirmation_tags_count` | INI | **Static config** | Default count is a rule, not a setting |
| `confirmation_tags_nature` | INI | **Static config** | This is an AI prompt! |

**Recommended Migration:**

**`ai_prompts.yaml`:**
```yaml
confirmation_tags:
  prompt: "short, lowercase, human-friendly topical nouns as used on FetLife; no hashtags; no emojis"
  default_count: 5
```

**INI (`[Hashtags]`):**
```ini
confirmation_to_sender = true  # Keep in INI (deployment toggle)
# Remove confirmation_tags_count and confirmation_tags_nature
```

**Status:** ✅ **Defaults added to `ai_prompts.yaml`**

---

### 3. OpenAI Prompts

**Currently in INI (`[openAI]` section):**
```ini
system_prompt = You write captions for FetLife...
role_prompt = Using the image analysis...
```

**Analysis:**
- These are **AI prompts** (static content)
- They're specific to FetLife use case
- Changes require testing, not just config edits

**Recommendation:** 
- ✅ **Keep in INI for now** (deployment-specific prompts)
- 📋 **Future:** Create `ai_prompts.fetlife.yaml` for FetLife-specific prompts
- 🔄 **Override mechanism:** Load base prompts from YAML, allow INI override

**Why keep in INI?**
- FetLife prompts are **highly customized** per user
- Different users may want different tones (kinky vs. artistic vs. technical)
- INI override is more flexible for this use case

---

## Migration Strategy

### Phase 1: Add Defaults to Static Config ✅ DONE

- ✅ Email platform behavior → `platform_limits.yaml`
- ✅ Confirmation tags prompt → `ai_prompts.yaml`

### Phase 2: Update Config Loader (Future)

Add static config fallback to INI parser:

```python
# In config/loader.py
def _get_email_caption_target(ini_value, static_config):
    """Get caption_target from INI or fall back to static config."""
    if ini_value:
        return ini_value
    return static_config.platform_limits.email.caption_target
```

### Phase 3: Deprecate INI Values (Future)

1. Log warning when deprecated INI values are used
2. Add migration guide to logs
3. Eventually remove INI parsing for migrated values

---

## Backward Compatibility

### Current Behavior (v2.6.0)

- ✅ INI values take precedence (if present)
- ✅ Static config provides defaults (if INI missing)
- ✅ **No breaking changes** — existing configs work unchanged

### Example: Email Configuration

**Scenario 1: INI specifies `caption_target`**
```ini
[Email]
caption_target = body
```
→ Uses `body` (INI wins)

**Scenario 2: INI omits `caption_target`**
```ini
[Email]
# caption_target not specified
```
→ Uses `subject` from `platform_limits.yaml` (static config fallback)

**Scenario 3: Custom static config**
```bash
export PV2_STATIC_CONFIG_DIR=/etc/publisher/config
```
→ Uses `/etc/publisher/config/platform_limits.yaml` defaults

---

## Benefits of Migration

### 1. Cleaner INI Files
```ini
# Before (43 lines)
[Email]
sender = user@gmail.com
recipient = upload@fetlife.com
smtp_server = smtp.gmail.com
smtp_port = 587
caption_target = subject
subject_mode = normal

[Hashtags]
confirmation_to_sender = true
confirmation_tags_count = 5
confirmation_tags_nature = short, lowercase, human-friendly topical nouns...

# After (6 lines)
[Email]
sender = user@gmail.com
recipient = upload@fetlife.com
smtp_server = smtp.gmail.com
smtp_port = 587

[Hashtags]
confirmation_to_sender = true
```

### 2. Versioned Defaults

Platform rules evolve with code and are tested together:
- FetLife changes caption length limit → update `platform_limits.yaml` + tests
- AI prompt refinement → update `ai_prompts.yaml` + verify output
- Git tracks changes with commit history

### 3. Easier Onboarding

New users get sane defaults without manual config:
```bash
# Minimal INI for new FetLife user
[Dropbox]
image_folder = /Photos/MyPhotos

[Content]
fetlife = true

[Email]
sender = me@gmail.com
recipient = upload@fetlife.com

# Everything else comes from static config!
```

### 4. Multi-Environment Consistency

Dev/staging/prod share same platform rules but different secrets:
```bash
# Dev: custom prompts for testing
export PV2_STATIC_CONFIG_DIR=/home/dev/custom-config

# Prod: standard prompts
# (uses default static config from package)
```

---

## Recommended Actions for Users

### For Existing Deployments

**Option 1: No Action Required (Safest)**
- Keep your existing INI files unchanged
- Static config provides defaults for missing values
- Zero risk of breakage

**Option 2: Clean Up INI (Recommended)**
1. Remove these lines from your INI:
   ```ini
   caption_target = subject
   subject_mode = normal
   confirmation_tags_count = 5
   confirmation_tags_nature = ...
   ```
2. Test that behavior is unchanged
3. Enjoy cleaner config files

**Option 3: Customize Static Config (Advanced)**
1. Copy `publisher_v2/config/static/` to custom directory
2. Edit YAML files with your preferences
3. Set `PV2_STATIC_CONFIG_DIR=/path/to/custom`
4. Remove corresponding INI values

### For New Deployments

**Minimal INI approach:**
```ini
[Dropbox]
image_folder = /Photos/MyPhotos
archive = archive

[Content]
archive = true
fetlife = true

[Email]
sender = me@gmail.com
recipient = 12345@upload.fetlife.com

# Everything else from static config!
```

---

## Testing Migration

### 1. Verify Static Config Loading

```bash
cd /Users/evert/Documents/GitHub/SocialMediaPythonPublisher
poetry run python -c "
from publisher_v2.config.static_loader import get_static_config
cfg = get_static_config()
print('Email caption_target:', cfg.platform_limits.email.caption_target)
print('Email subject_mode:', cfg.platform_limits.email.subject_mode)
print('Confirmation tags prompt:', cfg.ai_prompts.confirmation_tags.prompt)
print('Confirmation tags count:', cfg.ai_prompts.confirmation_tags.default_count)
"
```

Expected output:
```
Email caption_target: subject
Email subject_mode: normal
Confirmation tags prompt: short, lowercase, human-friendly topical nouns...
Confirmation tags count: 5
```

### 2. Test with Minimal INI

```bash
# Backup your INI
cp configfiles/fetlife.ini configfiles/fetlife.ini.backup

# Remove migrated values
vim configfiles/fetlife.ini
# (delete caption_target, subject_mode, confirmation_tags_*)

# Test preview mode
make preview-v2 CONFIG=configfiles/fetlife.ini

# Verify behavior is unchanged
# Restore backup if needed
```

---

## Future Enhancements

### Phase 2: Platform-Specific Prompt Overrides

```yaml
# ai_prompts.fetlife.yaml (future)
caption:
  system: >
    You write captions for FetLife email posts in a kinky, playful tone...
  role: >
    Using the image analysis, write 1–2 short sentences...
```

```python
# In config loader (future)
def load_platform_prompts(platform: str) -> dict:
    """Load platform-specific AI prompts if available."""
    try:
        return _load_yaml(f"ai_prompts.{platform}.yaml")
    except FileNotFoundError:
        return {}  # Fall back to base prompts
```

### Phase 3: Config Validation

```python
# Warn about deprecated INI values
if ini_has("Email", "caption_target"):
    logger.warning(
        "Email.caption_target in INI is deprecated. "
        "Use static config (platform_limits.yaml) or remove to use defaults."
    )
```

---

## Summary

### Migrated to Static Config ✅

| Setting | From | To | Status |
|---------|------|-----|--------|
| `caption_target` | `[Email]` | `platform_limits.yaml` | ✅ Default added |
| `subject_mode` | `[Email]` | `platform_limits.yaml` | ✅ Default added |
| `confirmation_tags_nature` | `[Hashtags]` | `ai_prompts.yaml` | ✅ Default added |
| `confirmation_tags_count` | `[Hashtags]` | `ai_prompts.yaml` | ✅ Default added |

### Staying in INI (Deployment-Specific)

| Setting | Location | Reason |
|---------|----------|--------|
| `sender`, `recipient` | `[Email]` | Secrets/deployment-specific |
| `smtp_server`, `smtp_port` | `[Email]` | Deployment-specific |
| `confirmation_to_sender` | `[Hashtags]` | User preference toggle |
| `system_prompt`, `role_prompt` | `[openAI]` | User-specific customization |

### Action Required

**None!** All changes are backward-compatible. Existing INI files work unchanged.

**Recommended:** Clean up INI files by removing migrated values to rely on static config defaults.

---

## See Also

- [Configuration Reference](../05_Configuration/CONFIGURATION.md)
- [Feature 012: Centralized Configuration](012_central-config-i18n-text.md)
- [Static Config Files](../../publisher_v2/src/publisher_v2/config/static/)

