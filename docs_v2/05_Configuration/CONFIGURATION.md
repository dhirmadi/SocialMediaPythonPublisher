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
| `OPENAI_API_KEY` | OpenAI API key (must start with `sk-`) | `sk-proj-...` |

**Orchestrator note (Epic 001):** In multi-tenant orchestrator mode, per-tenant secrets like `OPENAI_API_KEY` and `DROPBOX_REFRESH_TOKEN` are expected to be delivered **on demand** via the orchestrator credentials endpoint, not baked into dyno env vars. The dyno still needs global integration credentials (e.g., `DROPBOX_APP_KEY/SECRET`) and orchestrator service auth.

### Optional Secrets (Platform-Specific)

| Variable | Description | Required When |
|----------|-------------|---------------|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token | Telegram publishing enabled |
| `INSTA_PASSWORD` | Instagram account password | Instagram publishing enabled |
| `EMAIL_PASSWORD` | Email/SMTP app password | Email/FetLife publishing enabled |
| `WEB_AUTH_TOKEN` | Bearer token for web API auth | Web interface enabled |
| `WEB_AUTH_USER` | Basic auth username | Web interface enabled |
| `WEB_AUTH_PASS` | Basic auth password | Web interface enabled |
| `AUTH0_CLIENT_SECRET` | Auth0 OIDC client secret | Auth0 admin login enabled |
| `WEB_SESSION_SECRET` | Web session signing secret (cookie/session middleware) | Auth0 admin login enabled |
| `web_admin_pw` | Legacy admin password (deprecated by Auth0) | Only if using legacy admin password |

### Web Admin (Auth0) — Required Non-Secret Env Vars

These are required when enabling Auth0 login (Feature 020). They are not “secrets” except `AUTH0_CLIENT_SECRET` and `WEB_SESSION_SECRET` above.

| Variable | Description | Example |
|----------|-------------|---------|
| `AUTH0_DOMAIN` | Auth0 tenant domain | `example.eu.auth0.com` |
| `AUTH0_CLIENT_ID` | Auth0 client id | `abc123` |
| `AUTH0_AUDIENCE` | Optional API audience | `https://publisher-api` |
| `AUTH0_CALLBACK_URL` | Callback URL registered in Auth0 | `https://<host>/auth/callback` |
| `ADMIN_LOGIN_EMAILS` | CSV allowlist of admin emails | `me@x.com,you@y.com` |
| `AUTH0_ADMIN_EMAIL_ALLOWLIST` | Alternate allowlist env var (legacy alias) | `me@x.com,you@y.com` |

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

#### Quick Start (Minimal Config Vars)

Set these three required JSON config vars to enable env-first mode:

```bash
# Required for env-first mode
heroku config:set STORAGE_PATHS='{"root": "/Photos/MySocialMedia"}' -a YOUR_APP
heroku config:set PUBLISHERS='[{"type": "fetlife", "recipient": "user@fetlife.com"}]' -a YOUR_APP
heroku config:set OPENAI_SETTINGS='{}' -a YOUR_APP

# If using email/FetLife publisher
heroku config:set EMAIL_SERVER='{"sender": "bot@gmail.com", "smtp_server": "smtp.gmail.com", "smtp_port": 587}' -a YOUR_APP
```

#### Migration Steps

1. **Set new config vars** on a canary app (keep `FETLIFE_INI` initially for safety)
2. **Validate**: 
   - `/health` returns 200
   - Web UI loads
   - "Random image" works (Dropbox access)
   - Admin login works
3. **Check logs** for `Config source: env_vars` (not deprecation warnings)
4. **Remove legacy config vars**:
   ```bash
   heroku config:unset FETLIFE_INI CONFIG_PATH -a YOUR_APP
   heroku ps:restart -a YOUR_APP
   ```
5. **Validate again** — app should work without INI
6. **Roll out** to remaining pipeline apps (batch 5-10 at a time)

#### Procfile Update

Once all apps are migrated, update your Procfile:

**Old (INI-based):**
```
web: bash -lc 'mkdir -p configfiles && printf "%s\n" "$FETLIFE_INI" > configfiles/fetlife.ini && PYTHONPATH=publisher_v2/src uvicorn publisher_v2.web.app:app --host 0.0.0.0 --port $PORT'
```

**New (env-first):**
```
web: PYTHONPATH=publisher_v2/src uvicorn publisher_v2.web.app:app --host 0.0.0.0 --port $PORT
```

#### Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ConfigurationError: Either config_file_path...` | Missing required JSON env var | Set `STORAGE_PATHS`, `PUBLISHERS`, `OPENAI_SETTINGS` |
| `Invalid JSON in X` | Malformed JSON | Validate at jsonlint.com |
| `DEPRECATION: INI-based config...` | Falling back to INI | Add missing JSON env var for mentioned section |
| Publishing fails | Missing publisher secret | Set `TELEGRAM_BOT_TOKEN`, `EMAIL_PASSWORD`, or `INSTA_PASSWORD` |

See [Story 021-07: Heroku Pipeline Migration](../08_Epics/004_deployment_ops_modernization/021_config_env_consolidation/stories/07_heroku_pipeline_migration/021_07_heroku-pipeline-migration.md) for complete reference including all config var examples.

---

## 10. Orchestrator-Sourced Runtime Configuration (Epic 001)

This section explains **which configuration must live on the dyno** vs what is expected to be delivered **on demand** by the orchestrator in the upcoming multi-tenant runtime (Epic 001).

### 10.1 Operating modes (important)

- **Single-tenant (legacy INI)**: dyno env vars + `configfiles/*.ini` (deprecated).
- **Single-tenant (env-first / Feature 021)**: dyno env vars only (JSON groupings like `PUBLISHERS`, `STORAGE_PATHS`, etc.).
- **Multi-tenant (orchestrator runtime / Epic 001)**:
  - Dyno env vars contain only **global** settings + service auth (no per-tenant secrets).
  - Per-request, Publisher resolves tenant by host and fetches **runtime config** and **credentials** from the orchestrator.

### 10.2 Dyno-required environment variables (global, not per-tenant)

These must be configured on the single multi-tenant dyno fleet.

#### A) Orchestrator connectivity (service-to-service)

| Variable | Purpose |
|----------|---------|
| `ORCHESTRATOR_BASE_URL` | Base URL for orchestrator service API (no trailing slash) |
| `ORCHESTRATOR_SERVICE_TOKEN` | Bearer token for calling orchestrator `/v1/*` endpoints (secret; never log) |

See: `docs_v2/02_Specifications/ORCHESTRATOR_SERVICE_API_INTEGRATION_GUIDE.md` (Sections 1–2).

#### B) Global integrations (shared credentials / platform-level)

| Variable | Purpose |
|----------|---------|
| `DROPBOX_APP_KEY` / `DROPBOX_APP_SECRET` | Shared Dropbox OAuth app credentials used with per-tenant refresh tokens from orchestrator |
| `PV2_STATIC_CONFIG_DIR` (optional) | Override static YAML config directory for fleet-wide prompt/text tuning |

#### C) Web UI & Admin (Auth0 + HTTP auth)

In multi-tenant mode, the web UI still needs a consistent security posture per `.cursor/rules/20-web-ui-admin-security.mdc`.

| Variable(s) | Purpose |
|------------|---------|
| `WEB_AUTH_TOKEN` **or** `WEB_AUTH_USER`/`WEB_AUTH_PASS` | API-level auth gate for web endpoints |
| `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `AUTH0_CALLBACK_URL` | Auth0 OIDC login (Feature 020) |
| `ADMIN_LOGIN_EMAILS` (or `AUTH0_ADMIN_EMAIL_ALLOWLIST`) | Admin allowlist |
| `WEB_SESSION_SECRET` | Session signing secret |
| `WEB_ADMIN_COOKIE_TTL_SECONDS` | Admin cookie TTL (server-enforced clamp) |

### 10.3 Orchestrator-delivered runtime config (non-secret)

Publisher expects these values to come from `GET /v1/runtime/by-host?host=<normalized_host>` (cached by TTL):

- **`features`**: publish/analyze/keep/remove/auto_view toggles
- **`storage`**: provider + paths + `credentials_ref`
- **Additionally required for parity with Feature 021** (see Epic 001 “Delta / Change Request”):
  - publishers (telegram/email/instagram non-secret settings)
  - email server (smtp host/port/sender; no password)
  - ai settings (models/prompts; no API key)
  - captionfile settings
  - confirmation settings
  - content settings

### 10.4 Orchestrator-delivered credentials (secrets)

Publisher expects secrets to be returned only via `POST /v1/credentials/resolve`:

- **Storage provider secrets** (e.g., Dropbox refresh token)
- **Publisher secrets** (e.g., Telegram bot token, Email password, Instagram credential bundle)
- **AI provider secrets** (e.g., OpenAI API key)

Secrets must never be embedded in runtime config payloads and must never be persisted to disk by Publisher.

### 10.5 Reference links

- Epic 001: `docs_v2/08_Epics/001_multi_tenant_orchestrator_runtime_config/001_single-dyno_multi-tenant_domain-based_runtime-config.md`
- Orchestrator integration guide: `docs_v2/02_Specifications/ORCHESTRATOR_SERVICE_API_INTEGRATION_GUIDE.md`

## See Also

- [Feature 012: Central Config & i18n](../08_Epics/004_deployment_ops_modernization/012_central_config_i18n_text/012_feature.md)
- [i18n Activation Summary](../08_Epics/004_deployment_ops_modernization/012_central_config_i18n_text/stories/01_implementation/ACTIVATION_SUMMARY.md)
- [Feature 021: Config Env Consolidation](../08_Epics/004_deployment_ops_modernization/021_config_env_consolidation/021_feature.md)
- [Architecture Documentation](../03_Architecture/ARCHITECTURE.md)


