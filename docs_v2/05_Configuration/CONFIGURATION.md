# Configuration — Social Media Publisher V2

Version: 2.7  
Last Updated: December 23, 2025

---

## Overview

Publisher V2 uses a **three-layer configuration model** that cleanly separates:

1. **Secrets** — Sensitive credentials (`.env` only, never in repo)
2. **Dynamic Configuration** — Runtime toggles and deployment-specific settings (`.env` + `.ini`)
3. **Static Configuration** — AI prompts, platform limits, UI text, and service limits (versioned YAML files)

This separation enables:
- Safe secret management (no accidental commits)
- Feature flags and deployment customization without code changes
- AI prompt tuning and internationalization without redeploy

---

## 1. Secrets (Environment Variables Only)
**All secrets must be set via environment variables or `.env` file. Never commit secrets to the repository.**

### Required Secrets

| Variable | Description | Example |
|----------|-------------|---------|
| `DROPBOX_APP_KEY` | Dropbox OAuth app key | `abc123...` |
| `DROPBOX_APP_SECRET` | Dropbox OAuth app secret | `xyz789...` |
| `DROPBOX_REFRESH_TOKEN` | OAuth2 refresh token | `token123...` |
| `OPENAI_API_KEY` | OpenAI API key (must start with `sk-`) | `sk-proj-...` |

### Optional Secrets (Platform-Specific)

| Variable | Description | Required When |
|----------|-------------|---------------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | Telegram publishing enabled |
| `TELEGRAM_CHANNEL_ID` | Telegram channel/chat ID | Telegram publishing enabled |
| `INSTA_PASSWORD` | Instagram account password | Instagram publishing enabled |
| `EMAIL_PASSWORD` | Email/SMTP app password | Email/FetLife publishing enabled |
| `WEB_AUTH_TOKEN` | Bearer token for web API auth | Web interface enabled |
| `WEB_AUTH_USER` | Basic auth username | Web interface enabled |
| `WEB_AUTH_PASS` | Basic auth password | Web interface enabled |
| `web_admin_pw` | Admin mode password | Web admin features enabled |

---

## 2. Dynamic Configuration (Environment + INI)

Dynamic configuration controls runtime behavior and is split between environment variables and INI files.

### 2.1 Feature Toggles (Environment Variables)

Environment variables provide coarse-grained feature switches without editing INI files:

| Variable | Default | Behavior |
|----------|---------|----------|
| `FEATURE_ANALYZE_CAPTION` | `true` | When `false`, skips AI analysis, caption generation, and sidecar writes. |
| `FEATURE_PUBLISH` | `true` | When `false`, skips publishing (CLI + web); Web `/publish` returns HTTP 403. |
| `FEATURE_KEEP_CURATE` | `true` | When `false`, disables Keep curation action; buttons hidden, `/keep` returns 403. |
| `FEATURE_REMOVE_CURATE` | `true` | When `false`, disables Remove curation action; buttons hidden, `/remove` returns 403. |
| `AUTO_VIEW` | `false` | When `true`, allows non-admin users to view random images in web UI. |

**Accepted values:** `true/false`, `1/0`, `yes/no`, `on/off` (case-insensitive).  
**Invalid values:** Raise `ConfigurationError` at startup.

**Note:** Storage/Dropbox integration is always enabled (base feature, cannot be disabled).

### 2.2 Advanced Environment Overrides

| Variable | Purpose | Default |
|----------|---------|---------|
| `folder_keep` | Override `[Dropbox].folder_keep` | (from INI) |
| `folder_remove` | Override `[Dropbox].folder_remove` | (from INI) |
| `AI_RATE_PER_MINUTE` | Override OpenAI rate limit | 20 (from static config) |
| `PV2_STATIC_CONFIG_DIR` | Custom static config directory | `<package>/config/static` |
| `WEB_DEBUG` | Enable FastAPI debug mode | `false` |
| `WEB_SECURE_COOKIES` | Require HTTPS for cookies | `true` |
| `WEB_ADMIN_COOKIE_TTL_SECONDS` | Admin session TTL (60-3600) | 3600 |
| `CONFIG_PATH` | Path to INI config file (web only) | (required for web) |
| `ENV_PATH` | Path to `.env` file | `.env` |
| `PORT` | Web server port | 8000 |

### 2.3 INI Schema

**Note:** The config parser supports inline comments with `;` or `#`. Values are automatically stripped of trailing comments.

```ini
[Dropbox]
image_folder = /Photos/to_post
archive = archive
; Optional curation subfolders (relative to image_folder)
folder_keep = approve
folder_remove = remove          ; legacy configs may still use folder_reject

[Content]
hashtag_string = #photography #portrait   ; Note: ignored for Email/FetLife in V2
archive = true
debug = false

[openAI]
; Recommended: Separate models for optimal quality/cost balance
vision_model = gpt-4o           ; High-quality vision analysis
caption_model = gpt-4o-mini     ; Cost-effective caption generation

; OR use legacy single model (backward compatible):
; model = gpt-4o-mini           ; Use same model for both tasks

system_prompt = You are a senior social media copywriter...
role_prompt = Write a caption for:

; Stable-Diffusion sidecar (optional, defaults shown)
sd_caption_enabled = true
sd_caption_single_call_enabled = true
; sd_caption_model = gpt-4o-mini
; sd_caption_system_prompt = You are a fine-art photography curator...
; sd_caption_role_prompt = Write two outputs (caption, sd_caption) as JSON:

[Instagram]
name = my_username

[Email]
sender = me@gmail.com
recipient = someone@example.com
smtp_server = smtp.gmail.com
smtp_port = 587
; FetLife email behavior (caption placement and subject prefix)
caption_target = subject         ; subject | body | both
subject_mode = normal            ; normal | private | avatar
; Confirmation back to sender with tags
confirmation_to_sender = true
confirmation_tags_count = 5
confirmation_tags_nature = short, lowercase, human-friendly topical nouns; no hashtags; no emojis
```

## 3. OpenAI Model Selection (v2.1+)

### Recommended Configuration (Optimal Quality/Cost):
```ini
vision_model = gpt-4o           ; Superior vision analysis
caption_model = gpt-4o-mini     ; Excellent captions at low cost
```
**Cost:** ~$4.55 per 1,000 images | **Quality:** ⭐⭐⭐⭐⭐

### Budget Configuration:
```ini
model = gpt-4o-mini             ; Good quality for both tasks
```
**Cost:** ~$0.32 per 1,000 images | **Quality:** ⭐⭐⭐⭐

### Cost Comparison (per 1,000 images):
- **Both gpt-4o-mini:** $0.32 (budget mode)
- **Split (gpt-4o + gpt-4o-mini):** $4.55 ⭐ RECOMMENDED
- **Both gpt-4o:** $6.50 (overkill, not recommended)

### When to Use Each:
- **Photography/Art:** Use `gpt-4o` for vision (subtle details matter)
- **Casual/Social:** `gpt-4o-mini` for both (budget-friendly)
- **Production:** Split configuration (best quality/cost ratio)

### Backward Compatibility:
- Legacy `model` field still supported
- If only `model` is specified, it's used for both vision and caption
- New configs should use `vision_model` and `caption_model`

## 4. Stable‑Diffusion Caption Sidecar (v2.4+)

Generate an additional fine‑art, PG‑13 training caption and write `<image>.txt` next to the image. On archive, the sidecar moves with the image.

```ini
[openAI]
sd_caption_enabled = true                 ; Master switch (default: true)
sd_caption_single_call_enabled = true     ; Single JSON call with {caption, sd_caption}
sd_caption_model = gpt-4o-mini            ; Optional override (defaults to caption_model)
sd_caption_system_prompt = ...            ; Optional override
sd_caption_role_prompt = ...              ; Optional override

[CaptionFile]
; Phase 2 extended contextual metadata in sidecar (PG-13, artistic/contextual)
extended_metadata_enabled = false
```

Behavior:
- When enabled, the caption generator prefers a single call returning `{caption, sd_caption}`.
- On error or if disabled, falls back to legacy caption‑only path.
- Sidecar write is skipped in preview/dry/debug modes and does not block publishing.
- SD caption file (`<image>.txt`) format:
  - **One line only**: the `sd_caption` text (no metadata)
  - Overwritten on re-processing

## 5. Validation Rules (Pydantic)

- Dropbox folder must start with `/`
- `OPENAI_API_KEY` must start with `sk-`
- Model names must start with `gpt-4`, `gpt-3.5`, `o1`, or `o3`
- If Telegram enabled, both token and channel ID are required
- Feature toggle values must be valid booleans (`true/false/1/0/yes/no/on/off`)
- Keep/remove folder names must not contain path separators or `..`
- SMTP port int in {25,465,587}; default 587
- archive/debug booleans parsed strictly
- Email caption placement validation:
  - caption_target ∈ {subject, body, both}
  - subject_mode ∈ {normal, private, avatar}

## 6. Preview Mode (v2.2+)

Test your configuration without publishing or modifying anything:

```bash
# Preview with specific config
make preview-v2 CONFIG=configfiles/fetlife.ini

# Or direct command
PYTHONPATH=publisher_v2/src uv run python publisher_v2/src/publisher_v2/app.py \
  --config configfiles/fetlife.ini \
  --preview

# Preview specific image
PYTHONPATH=publisher_v2/src uv run python publisher_v2/src/publisher_v2/app.py \
  --config configfiles/fetlife.ini \
  --select image.jpg \
  --preview
```

**Preview Mode Guarantees:**
- ✅ Full AI pipeline runs (vision + caption)
- ✅ Human-readable output showing all details
- ✅ No content published to any platform
- ✅ No images moved/archived on Dropbox
- ✅ No state/cache updates
- ✅ Can preview same image multiple times

---

## 7. Configuration Reference Summary

| Layer | Source | Scope | Example |
|-------|--------|-------|---------|
| **Secrets** | `.env` only | Credentials | `OPENAI_API_KEY`, `DROPBOX_APP_KEY` |
| **Dynamic** | `.env` + INI | Runtime toggles | `FEATURE_PUBLISH`, `[Content].archive` |
| **Static** | YAML files | Prompts, limits, text | `ai_prompts.yaml`, `web_ui_text.en.yaml` |

### Configuration Load Order

1. **Environment variables** loaded from `.env` (if present)
2. **INI file** parsed and validated
3. **Static config YAMLs** loaded from `config/static/` (or `$PV2_STATIC_CONFIG_DIR`)
4. **Pydantic validation** applied to all layers
5. **Secrets** extracted from environment only
6. **ApplicationConfig** instance created with all three layers

### Best Practices

✅ **DO:**
- Keep secrets in `.env` (never commit)
- Use environment vars for feature toggles
- Edit YAML files for prompt tuning and i18n
- Override static config dir for per-environment customization
- Use INI for deployment-specific folders and platform enablement

❌ **DON'T:**
- Put secrets in INI or YAML files
- Hard-code prompts or UI text in Python/HTML
- Edit static YAML defaults directly (override with custom dir instead)
- Change feature flags in code (use env vars)

---

## 8. V2 Env-First Configuration (Feature 021)

**Version 2.7+** introduces a **env-first configuration model** that consolidates INI-based settings into structured JSON environment variables. This aligns with the future Orchestrator API contract (Epic 001) while maintaining backward compatibility.

### 8.1 Why Env-First?

- **Single source of truth**: All runtime config in one place (`.env` or platform config vars)
- **Heroku/container friendly**: No need for INI file bootstrap
- **Auditable secrets**: Secrets remain flat env vars, separate from grouped settings
- **Future-ready**: Matches the Orchestrator API's database-backed config model

### 8.2 New JSON Environment Variables

| Variable | Purpose | Required |
|----------|---------|----------|
| `STORAGE_PATHS` | Dropbox folder configuration | For env-first mode |
| `PUBLISHERS` | Publisher array (telegram, fetlife, instagram) | For env-first mode |
| `EMAIL_SERVER` | SMTP configuration (for email publishers) | If email publisher used |
| `OPENAI_SETTINGS` | AI model settings | No (has defaults) |
| `CAPTIONFILE_SETTINGS` | Caption file metadata options | No |
| `CONFIRMATION_SETTINGS` | Email confirmation behavior | No |
| `CONTENT_SETTINGS` | Hashtags, archive, debug flags | No |

### 8.3 Example: Minimal Env-First Configuration

```bash
# Secrets (flat env vars)
OPENAI_API_KEY=sk-xxx
DROPBOX_APP_KEY=xxx
DROPBOX_APP_SECRET=xxx
DROPBOX_REFRESH_TOKEN=xxx
TELEGRAM_BOT_TOKEN=123456:ABC-xxx

# JSON env vars
STORAGE_PATHS={"root": "/Photos/MySocialMedia"}
PUBLISHERS=[{"type": "telegram", "channel_id": "@my_channel"}]
```

### 8.4 Example: Full FetLife/Email Configuration

```bash
# Secrets
OPENAI_API_KEY=sk-xxx
DROPBOX_APP_KEY=xxx
DROPBOX_APP_SECRET=xxx
DROPBOX_REFRESH_TOKEN=xxx
EMAIL_PASSWORD=your-app-password

# JSON env vars
STORAGE_PATHS={"root": "/Photos/MySocialMedia", "archive": "sent", "keep": "favorites", "remove": "trash"}
PUBLISHERS=[{"type": "fetlife", "recipient": "user@fetlife.com", "caption_target": "subject", "subject_mode": "normal"}]
EMAIL_SERVER={"sender": "mybot@gmail.com", "smtp_server": "smtp.gmail.com", "smtp_port": 587}
CONFIRMATION_SETTINGS={"confirmation_to_sender": true, "confirmation_tags_count": 5}
CONTENT_SETTINGS={"archive": true, "debug": false}
```

### 8.5 Precedence Order

Configuration values are loaded in this order (first found wins):

1. **New JSON env vars** (PUBLISHERS, EMAIL_SERVER, STORAGE_PATHS, etc.)
2. **Old individual env vars** (TELEGRAM_CHANNEL_ID, folder_keep, etc.)
3. **INI file sections** (deprecated fallback)

### 8.6 Deprecation Warnings

When INI fallback is used, the loader emits a warning:

```
DEPRECATION: INI-based config is deprecated. Migrate to JSON env vars 
(PUBLISHERS, EMAIL_SERVER, STORAGE_PATHS, etc.). INI sections used: [Content, Email, openAI]
```

---

## 9. Migration Guide {#migration}

### 9.1 From INI to Env-First

| INI Section | INI Field | New Env Var |
|-------------|-----------|-------------|
| `[Dropbox]` | `image_folder` | `STORAGE_PATHS.root` |
| `[Dropbox]` | `archive` | `STORAGE_PATHS.archive` |
| `[Dropbox]` | `folder_keep` | `STORAGE_PATHS.keep` |
| `[Dropbox]` | `folder_remove` | `STORAGE_PATHS.remove` |
| `[Content]` | `telegram=true` | `PUBLISHERS` array with `{"type": "telegram", ...}` |
| `[Content]` | `fetlife=true` | `PUBLISHERS` array with `{"type": "fetlife", ...}` |
| `[Content]` | `instagram=true` | `PUBLISHERS` array with `{"type": "instagram", ...}` |
| `[Content]` | `hashtag_string` | `CONTENT_SETTINGS.hashtag_string` |
| `[Content]` | `archive` | `CONTENT_SETTINGS.archive` |
| `[Content]` | `debug` | `CONTENT_SETTINGS.debug` |
| `[Email]` | `sender` | `EMAIL_SERVER.sender` |
| `[Email]` | `smtp_server` | `EMAIL_SERVER.smtp_server` |
| `[Email]` | `smtp_port` | `EMAIL_SERVER.smtp_port` |
| `[Email]` | `recipient` | `PUBLISHERS[].recipient` (in fetlife entry) |
| `[Email]` | `caption_target` | `PUBLISHERS[].caption_target` (in fetlife entry) |
| `[Email]` | `subject_mode` | `PUBLISHERS[].subject_mode` (in fetlife entry) |
| `[Email]` | `confirmation_*` | `CONFIRMATION_SETTINGS.*` |
| `[openAI]` | `vision_model` | `OPENAI_SETTINGS.vision_model` |
| `[openAI]` | `caption_model` | `OPENAI_SETTINGS.caption_model` |
| `[openAI]` | `system_prompt` | `OPENAI_SETTINGS.system_prompt` |
| `[openAI]` | `sd_caption_*` | `OPENAI_SETTINGS.sd_caption_*` |
| `[CaptionFile]` | `*` | `CAPTIONFILE_SETTINGS.*` |
| `[Instagram]` | `name` | `PUBLISHERS[].username` (in instagram entry) |

### 9.2 Step-by-Step Migration

1. **Copy** `dotenv.v2.example` to `.env`
2. **Set secrets** (OpenAI, Dropbox, publisher-specific)
3. **Build STORAGE_PATHS** from your `[Dropbox]` section
4. **Build PUBLISHERS** from `[Content]` toggles + publisher sections
5. **Build EMAIL_SERVER** from `[Email]` (if using email publisher)
6. **Set optional settings** (CONTENT_SETTINGS, CAPTIONFILE_SETTINGS, etc.)
7. **Test** with preview mode: `make preview-v2`
8. **Remove** INI file dependency once validated

### 9.3 Heroku Migration

For Heroku apps using `FETLIFE_INI`:

1. Set new config vars on a canary app (keep `FETLIFE_INI` initially)
2. Validate: `/health` returns 200, web UI works, admin login works
3. Remove `FETLIFE_INI` config var and restart
4. Validate again
5. Roll out to remaining pipeline apps

See [Story 021-07: Heroku Pipeline Migration](../08_Features/021_config_env_consolidation/stories/07_heroku_pipeline_migration/021_07_heroku-pipeline-migration.md) for detailed instructions.

---

## See Also

- [Feature 012: Central Config & i18n](../08_Features/012_central_config_i18n_text/012_feature.md)
- [i18n Activation Summary](../08_Features/012_central_config_i18n_text/stories/01_implementation/ACTIVATION_SUMMARY.md)
- [Feature 021: Config Env Consolidation](../08_Features/021_config_env_consolidation/021_feature.md)
- [Architecture Documentation](../03_Architecture/ARCHITECTURE.md)


