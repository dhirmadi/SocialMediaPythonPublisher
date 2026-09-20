# Configuration — Social Media Publisher V2

Version: 2.8
Last Updated: December 30, 2025

---

## Overview

Publisher V2 uses a **three-layer configuration model** that cleanly separates:

1. **Secrets** — Sensitive credentials (`.env` only, never in repo)
2. **Dynamic Configuration** — Runtime toggles and deployment-specific settings (environment variables; `.env` locally)
3. **Static Configuration** — AI prompts, platform limits, UI text, and service limits (versioned YAML files)

This separation enables:
- Safe secret management (no accidental commits)
- Feature flags and deployment customization without code changes
- AI prompt tuning and internationalization without redeploy

**Default mode (production): Orchestrator-backed configuration**
In production, Publisher V2 runs in **orchestrator mode** (Epic 001 / Feature 022):

- The orchestrator is the **source of truth** for per-tenant runtime config (non-secret) and credential references.
- Publisher retrieves runtime config by host and resolves secrets on-demand via the orchestrator credentials endpoint.

Canonical GUI/validation contract for orchestrator-managed config fields:

- `docs_v2/02_Specifications/ORCHESTRATOR_RUNTIME_CONFIG_SCHEMA_REFERENCE.md`

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

### Web Admin (Auth0) — Required Non-Secret Env Vars

Auth0 is the only admin login (#137). Without `AUTH0_DOMAIN` and `AUTH0_CLIENT_ID` admin mode is unavailable and the UI says so. These are required when enabling Auth0 login (Feature 020). They are not “secrets” except `AUTH0_CLIENT_SECRET` and `WEB_SESSION_SECRET` above.

| Variable | Description | Example |
|----------|-------------|---------|
| `AUTH0_DOMAIN` | Auth0 tenant domain | `example.eu.auth0.com` |
| `AUTH0_CLIENT_ID` | Auth0 client id | `abc123` |
| `AUTH0_AUDIENCE` | Optional API audience | `https://publisher-api` |
| `AUTH0_CALLBACK_URL` | Callback URL registered in Auth0 | `https://<host>/auth/callback` |
| `ADMIN_LOGIN_EMAILS` | CSV allowlist of admin emails | `me@x.com,you@y.com` |
| `AUTH0_ADMIN_EMAIL_ALLOWLIST` | Alternate allowlist env var (legacy alias) | `me@x.com,you@y.com` |

---

## 2. Dynamic Configuration (Environment Variables)

> **INI support removed (#97 stage 4).** Configuration is environment-only: the JSON env vars
> `STORAGE_PATHS`, `PUBLISHERS`, `OPENAI_SETTINGS` are required; `EMAIL_SERVER`,
> `CONTENT_SETTINGS`, `CAPTIONFILE_SETTINGS`, `CONFIRMATION_SETTINGS` are optional.
> The CLI still accepts `--config <file>` for compatibility but ignores the file and logs a
> warning. Orchestrator runtime schema v1 was removed at the same time — schema v2 only.

### 2.1 Feature Toggles (Environment Variables)

Environment variables provide coarse-grained feature switches without editing INI files:

| Variable | Default | Behavior |
|----------|---------|----------|
| `FEATURE_ANALYZE_CAPTION` | `true` | When `false`, skips AI analysis, caption generation, and sidecar writes. |
| `FEATURE_PUBLISH` | `true` | When `false`, skips publishing (CLI + web); Web `/publish` returns HTTP 403. |
| `FEATURE_KEEP_CURATE` | `true` | When `false`, disables Keep curation action; buttons hidden, `/keep` returns 403. |
| `FEATURE_REMOVE_CURATE` | `true` | When `false`, disables Remove curation action; buttons hidden, `/remove` returns 403. |
| `FEATURE_DELETE` | `false` | When `true`, enables the permanent-delete action in the admin review workflow. |
| `FEATURE_AUTO_VIEW` | `false` | When `true`, allows non-admin users to view random images in web UI. (`AUTO_VIEW` still works as a deprecated alias and logs a warning; `FEATURE_AUTO_VIEW` wins when both are set.) |
| `FEATURE_ALT_TEXT` | `true` | When `false`, AI alt text is not attached to published images. |
| `FEATURE_SMART_HASHTAGS` | `true` | When `false`, disables smart hashtag generation. |
| `FEATURE_VOICE_MATCHING` | unset → on when `CONTENT_SETTINGS.voice_profile` is set, else off | Brand-voice caption matching. Unset: derived from the voice profile (#131). Set `true`/`false` to force it; an explicit value always wins. |
| `FEATURE_STORAGE_OPS_METERING` | `false` | When `true`, meters managed-storage operations to the orchestrator (orchestrator mode only). |
| `FEATURE_LIBRARY` | auto | Overrides the library UI flag. Unset: auto-enabled when managed storage is configured, off for Dropbox-only. |

**Accepted values:** `true/false`, `1/0`, `yes/no`, `on/off` (case-insensitive).
**Invalid values:** Raise `ConfigurationError` at startup.

> **Deploy order for `FEATURE_VOICE_MATCHING` (#131).** In orchestrator mode
> this flag became `bool | null`. Publisher must ship that handling before the
> orchestrator sends `null` or omits the field, and must not be rolled back
> past it afterwards. An older build treats `null` as a parse failure: it
> fails for any tenant without a warm cache entry — cold start, a new dyno, a
> first request — and serves stale config for the rest. An outage, not a
> degraded default, and one that looks fine for a few minutes on a warm dyno.

**Note:** Storage/Dropbox integration is always enabled (base feature, cannot be disabled).

### 2.2 Advanced Environment Overrides

Runtime tunables below the web/auth bootstrap layer are parsed centrally in `publisher_v2/config/runtime_settings.py` (#97 stage 2).

**When a change takes effect (#143).** Everything parsed into `RuntimeSettings` is read **once, at process start** (the FastAPI lifespan) and then carried by the components built from it. Changing such a variable in a running process has no effect — `heroku config:set` restarts the dyno, so it applies there, but a locally started `uvicorn` needs a restart. The variables still read per request, because they belong to the auth/bootstrap layer rather than to the tunables snapshot, are `WEB_AUTH_TOKEN`, `WEB_AUTH_USER`, `WEB_AUTH_PASS`, `WEB_ALLOW_UNAUTHENTICATED`, `WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE`, `WEB_ADMIN_COOKIE_EPOCH`, `WEB_ADMIN_COOKIE_TTL_SECONDS`, `AUTH0_DOMAIN`/`AUTH0_CLIENT_ID` and the signing-secret trio `WEB_SESSION_SECRET`/`SECRET_KEY`/`WEB_DEV_INSECURE_SECRET` — that is, exactly the variables `web/auth.py` reads, which `tests/test_env_centralization.py` pins by name.

| Variable | Purpose | Default |
|----------|---------|---------|
| `folder_keep` | Override `[Dropbox].folder_keep` | (from INI) |
| `folder_remove` | Override `[Dropbox].folder_remove` | (from INI) |
| `AI_RATE_PER_MINUTE` | Override OpenAI rate limit | 20 (from static config) |
| `PV2_STATIC_CONFIG_DIR` | Custom static config directory. A directory written before #138 may still contain `platform_captions.*.examples`; that key is stripped with a `static_caption_examples_ignored` warning rather than failing the load, since the app reads this at startup on every instance | `<package>/config/static` |
| `WEB_DEBUG` | Enable FastAPI debug/verbose logging **only** — it no longer enables the insecure dev signing secret (#87 SEC-5) | `false` |
| `WEB_DEV_INSECURE_SECRET` | Explicit local-dev opt-in for the built-in insecure session/cookie signing secret when `WEB_SESSION_SECRET` is unset. **Never set in production.** | `false` |
| `WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE` | Strict mode (#91 SEC-3): require Bearer/Basic header auth in addition to the admin cookie when a header backend is configured | `false` |
| `WEB_ADMIN_COOKIE_EPOCH` | Cookie kill switch (#91 SEC-10): rotate the value to invalidate every outstanding admin cookie without changing `WEB_SESSION_SECRET` | (empty) |
| `WEB_SECURE_COOKIES` | Require HTTPS for cookies: sends the admin cookie with `Secure`, and enables HSTS. Truthy values are `1`, `true`, `yes`, `on` (case-insensitive); anything else is off. Until #143 the cookie flag alone used a narrower set that excluded `on`, so `WEB_SECURE_COOKIES=on` sent HSTS but a cookie without `Secure` | `true` |
| `WEB_ADMIN_COOKIE_TTL_SECONDS` | Admin session TTL (60-3600) | 3600 |
| `WEB_TRUST_FORWARDED_FOR` | Trust the proxy's forwarded headers. Set to `true` **only behind a proxy that appends the real client IP as the rightmost `X-Forwarded-For` entry and sets `X-Forwarded-Proto`** (Heroku router contract). Rate limits key on the rightmost `X-Forwarded-For` entry (everything left of it is client-supplied); the CSRF same-origin check and the Auth0 callback URL take the scheme from `X-Forwarded-Proto` (`http`/`https` only), and only when every value it carries agrees — a header whose values disagree is not trusted and the scheme falls back to the connection's own. **Required on Heroku**: without it every browser `POST` under `/api` returns 403 "CSRF check failed" (#129). | `false` |
| `DATABASE_URL` | Postgres URL. Enables caption history **and** the per-platform publish records/lease (`pv2_publish_record`, #85). **Absent:** both degrade to the legacy file-based posted-state (`~/.cache/publisher_v2/posted.json`) — no per-platform retry granularity: a partial publish records the image as posted (any-success semantics) and failed platforms are not retried automatically. Concurrent publishes of the same image are then serialized **in-process only** (#139): run a single web worker without a database, or set `DATABASE_URL` so the DB lease covers multi-worker deployments. | (unset) |
| `PUBLISH_TIMEOUT_SECONDS` | Default per-publisher timeout (min 5s) | 120 |
| `PUBLISH_TIMEOUT_<PLATFORM>_SECONDS` | Per-platform publish timeout override (e.g. `PUBLISH_TIMEOUT_TELEGRAM_SECONDS`) | (default timeout) |
| `AI_STAGE_TIMEOUT_SECONDS` | Hard deadline for the combined vision+caption stage (min 0.1s) | 150 |
| `PUBLISH_LEASE_TTL_SECONDS` | Age after which a `leased` publish record is treated as orphaned (its run crashed) and can be re-leased. Floored at `AI_STAGE_TIMEOUT_SECONDS + slowest publish timeout + 60s` so a live lease is never reclaimed mid-publish; the floor excludes image download/variant rendering, so keep well above the floor on slow storage. `0` (and any value below the floor) is raised to the floor rather than disabling reclaim — there is no way to turn the TTL off (#139) | 600 |
| `WEB_IMAGE_CACHE_TTL_SECONDS` | Override web image-listing cache TTL | (from static config) |
| `WEB_THUMBNAIL_CACHE_TTL_SECONDS` | Managed-storage thumbnail cache TTL. A hit inside the TTL costs zero storage ops; past it the object's ETag is re-checked (#140). The cache is **per process** and is invalidated by writes made through that same process — run a single web worker, or lower the TTL, if you scale out | 900 |
| `PV2_CAPTION_HISTORY_RETENTION_DAYS` | Caption history retention window | 90 |
| `TENANT_SERVICE_CACHE_MAX_SIZE` | Max cached tenant services (orchestrator mode) | 1000 |
| `TENANT_SERVICE_TTL_SECONDS` | Tenant service cache TTL | 600 |
| `LIBRARY_MAX_UPLOAD_MB` | Library upload size cap | 20 |
| `LIBRARY_SCAN_BUDGET` | Library listing scan budget (objects per request) | 5000 |
| `CONFIG_PATH` | Deprecated (#97 stage 4): INI removed; value is ignored | (unused) |
| `ENV_PATH` | Path to `.env` file | `.env` |
| `PORT` | Web server port | 8000 |

### Removed

- 2026-09-19 (#137): the password admin login is removed: the `web_admin_pw` env var, `POST /api/admin/login`, `verify_admin_password` and `WEB_LOGIN_BACKOFF_CAP_SECONDS` no longer exist. Auth0 is the only admin login; admin cookies minted by the old password route are rejected. Analyze, publish, keep, remove and delete now always require the Auth0 admin cookie: a `WEB_AUTH_TOKEN`/Basic header alone gets 503 (no Auth0 configured) or 403 (no admin cookie), and a tenant without Auth0 gets 403. `WEB_ALLOW_UNAUTHENTICATED` no longer opens these routes either.
  **Operator step on rollout:** nothing reads `web_admin_pw` any more, but a value left on an existing
  instance is a live-looking credential that `scripts/heroku_hetzner_clone.py` will copy into every
  clone. Run `heroku config:unset web_admin_pw` (or the equivalent) on each instance once this is
  deployed.

### 2.3 INI Schema (REMOVED — historical reference only)

> The INI path was deleted in #97 stage 4. The schema below is kept only to help
> migrate old `*.ini` files to the JSON env vars in section 2.4/3.

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

; Defaults now come from ai_prompts.yaml (#138): the persona under caption.system,
; the multi-platform brief under caption.role, and the single-platform one under
; caption.role_single. A tenant system_prompt replaces the persona; the
; banned-constructions rules under caption.rules are appended to it either way,
; so setting your own persona does not lose them.
system_prompt = You write as ...  ; your own persona; rules are appended
role_prompt = Write one caption per platform below about this photograph.

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
# Preview (configuration comes from the environment)
make preview-v2

# Or direct command
PYTHONPATH=publisher_v2/src uv run python publisher_v2/src/publisher_v2/app.py --preview

# Preview specific image
PYTHONPATH=publisher_v2/src uv run python publisher_v2/src/publisher_v2/app.py \
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

### Caption prompt keys in `ai_prompts.yaml` (#138)

| Key | Role |
|---|---|
| `caption.system` | The persona. A tenant `OPENAI_SETTINGS.system_prompt` replaces it. |
| `caption.rules` | Banned constructions. **Appended to whichever persona is in force**, so a tenant that writes its own persona keeps them. |
| `caption.role` | The brief used when several platforms are written in one call. |
| `caption.role_single` | The brief used by the single-platform fallbacks, which send one `Platform=` line. |
| `platform_captions.<p>.closing` | `question`, `statement` or `any`. When set, the "recent closing pattern to avoid" constraint is skipped — a mandated closing cannot also be forbidden. |
| `platform_captions.<p>.examples` | **Not supported.** Stripped with a warning; the tenant voice profile is the only source of examples. |

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

# Optional (#97 stage 3): "use_tls" (default true, STARTTLS) and "smtp_username"
# (login user; defaults to sender). Orchestrator mode maps email_server.use_tls /
# email_server.username to the same fields. SMTP socket timeout comes from
# service_limits.yaml smtp.timeout_seconds (fallback 30s).
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

Set these three required JSON config vars to enable env-first mode, plus `WEB_TRUST_FORWARDED_FOR=true` for the web UI:

```bash
# Required for env-first mode
heroku config:set STORAGE_PATHS='{"root": "/Photos/MySocialMedia"}' -a YOUR_APP
heroku config:set PUBLISHERS='[{"type": "fetlife", "recipient": "user@fetlife.com"}]' -a YOUR_APP
heroku config:set OPENAI_SETTINGS='{}' -a YOUR_APP

# Required on every Heroku app for the web UI (#129): without it every browser POST under /api
# returns 403 "CSRF check failed". Do not set FORWARDED_ALLOW_IPS; it is not used (see §10.2).
heroku config:set WEB_TRUST_FORWARDED_FOR=true -a YOUR_APP

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

This section explains **which configuration must live on the dyno** vs what is expected to be delivered **on demand** by the orchestrator in the multi-tenant runtime (Epic 001).

### 10.1 Operating modes (important)

- **Multi-tenant (orchestrator runtime / Epic 001, Feature 022)** (**default production mode**):
  - Dyno env vars contain only **global** settings + service auth (no per-tenant secrets).
  - Per-request, Publisher resolves tenant by host and fetches **runtime config** and **credentials** from the orchestrator.
- **Single-tenant (env-first / Feature 021)**: dyno env vars only (JSON groupings like `PUBLISHERS`, `STORAGE_PATHS`, etc.). Useful for local/dev and single-tenant deployments.
- *(Historical: a single-tenant INI mode existed until #97 stage 4 removed it. `--config` is still accepted for compatibility but the file is ignored.)*

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
| `PV2_STATIC_CONFIG_DIR` (optional) | Override static YAML config directory for fleet-wide prompt/text tuning. `caption.system` is the persona, `caption.rules` is appended to whichever persona is in force, `caption.role`/`caption.role_single` are the multi- and single-platform briefs, and a leftover `examples:` key is stripped with a warning (#138) |

#### C) Web UI & Admin (Auth0 + HTTP auth)

In multi-tenant mode, the web UI still needs a consistent security posture per `.cursor/rules/20-web-ui-admin-security.mdc`.

| Variable(s) | Purpose |
|------------|---------|
| `WEB_AUTH_TOKEN` **or** `WEB_AUTH_USER`/`WEB_AUTH_PASS` | API-level auth gate for web endpoints |
| `AUTH0_DOMAIN`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`, `AUTH0_CALLBACK_URL` | Auth0 OIDC login (Feature 020) |
| `ADMIN_LOGIN_EMAILS` (or `AUTH0_ADMIN_EMAIL_ALLOWLIST`) | Admin allowlist |
| `WEB_SESSION_SECRET` | Session signing secret |
| `WEB_ADMIN_COOKIE_TTL_SECONDS` | Admin cookie TTL (server-enforced clamp) |
| `WEB_TRUST_FORWARDED_FOR` | Set `true` on Heroku so per-IP rate limits key on the rightmost `X-Forwarded-For` entry (the router-appended real client IP) and CSRF/Auth0 read the scheme from `X-Forwarded-Proto`. **Required on Heroku** (#129) |

**Heroku proxy headers (#129).** Heroku's router is not a loopback peer, so uvicorn's own proxy-header handling (`--proxy-headers`, trusted peers from `FORWARDED_ALLOW_IPS`, default `127.0.0.1`) never rewrites the request scheme there, and the `Procfile` deliberately does not pass `--forwarded-allow-ips="*"`. `FORWARDED_ALLOW_IPS` is **not used**; do not set it. The one env var Heroku requires for proxy headers is:

```bash
heroku config:set WEB_TRUST_FORWARDED_FOR=true -a YOUR_APP
```

**Do not set this flag unless a proxy really is in front of the app.** With it
set on a directly exposed instance there is no proxy value to disagree with,
so whatever the client sends is the only value present and is trusted — the
scheme becomes "whatever the caller claims". That is the flag's documented
contract rather than a defect in the parsing, and no parsing rule can detect
it; the blast radius is the scheme half of the CSRF same-origin comparison
(the host half is still the real `Host` header) and the localhost branch of
the Auth0 callback.

If the flag is missing on a dyno the app now says so once at startup
(`forwarded_headers_untrusted_on_heroku`), and a CSRF rejection caused by it
carries a `hint` naming the flag — the plain "cross-origin Origin" reason on
its own points at the browser rather than at the proxy.

**Double proxy (Cloudflare in front of Heroku).** `X-Forwarded-Proto` is
honoured only when every value it carries agrees. No position in a disagreeing
list is trustworthy: if a client sends `X-Forwarded-Proto: https` and a proxy
appends its own `http`, the leftmost entry is the client's forgery, so the app
falls back to the connection's scheme instead of guessing.

With Cloudflare's SSL mode set to **Flexible**, Cloudflare terminates TLS and
connects to Heroku over plain HTTP. The forwarded values then genuinely
disagree (`https` from Cloudflare, `http` for the hop Heroku saw), the scheme
falls back to `http`, and the 403 returns while the browser's `Origin` is
`https://…`. `WEB_TRUST_FORWARDED_FOR` does not fix it, because the header is
telling the truth about a downgraded hop. Use **Full** or **Full (strict)**,
where both hops are HTTPS, the values agree, and the scheme resolves to
`https`. Where the chain appends its value, that 403 is logged with a `hint`
naming the disagreement rather than the generic cross-origin reason. Where the
nearest proxy overwrites instead, the header simply agrees on `http`, the
scheme resolves to `http` and the 403 carries no hint — the app cannot tell
that case apart from a genuinely plain-HTTP deployment.

### 10.3 Orchestrator-delivered runtime config (non-secret)

Publisher expects these values to come from the orchestrator **runtime config** endpoint (cached by TTL).
**Note:** Publisher prefers **POST** for runtime lookup (Feature 022), with **GET fallback** on 405.

- **`features`**: publish/analyze/keep/remove/auto_view toggles
- **`storage`**: provider + paths + `credentials_ref`
- **Schema v2 (Feature 022)** also includes the env-first “parity” blocks (all **non-secret**):
  - **`publishers[]`**: publisher configs (e.g., telegram channel id, fetlife recipient, instagram username)
  - **`email_server`**: SMTP server settings (**no password**, only `password_ref`)
  - **`ai`**: AI settings (**no API key**, only `credentials_ref`)
  - **`captionfile`**: caption file settings
  - **`confirmation`**: confirmation behavior settings
  - **`content`**: archive/debug/hashtags and related content settings

### 10.4 Orchestrator-delivered credentials (secrets)

Publisher expects secrets to be returned only via `POST /v1/credentials/resolve`:

- **Storage provider secrets** (e.g., Dropbox refresh token)
- **Publisher secrets** (e.g., Telegram bot token, Email password, Instagram credential bundle)
- **AI provider secrets** (e.g., OpenAI API key)

Secrets must never be embedded in runtime config payloads and must never be persisted to disk by Publisher.

### 10.5 Reference links

- Epic 001: `docs_v2/08_Epics/001_multi_tenant_orchestrator_runtime_config/001_single-dyno_multi-tenant_domain-based_runtime-config.md`
- Orchestrator integration guide: `docs_v2/02_Specifications/ORCHESTRATOR_SERVICE_API_INTEGRATION_GUIDE.md`
- Feature 022 (schema v2 integration): `docs_v2/08_Epics/001_multi_tenant_orchestrator_runtime_config/022_orchestrator_schema_v2_integration/022_feature.md`
- Orchestrator GUI validation contract (canonical field reference): `docs_v2/02_Specifications/ORCHESTRATOR_RUNTIME_CONFIG_SCHEMA_REFERENCE.md`

## See Also

- [Feature 012: Central Config & i18n](../08_Epics/004_deployment_ops_modernization/012_central_config_i18n_text/012_feature.md)
- [i18n Activation Summary](../08_Epics/004_deployment_ops_modernization/012_central_config_i18n_text/stories/01_implementation/ACTIVATION_SUMMARY.md)
- [Feature 021: Config Env Consolidation](../08_Epics/004_deployment_ops_modernization/021_config_env_consolidation/021_feature.md)
- [Architecture Documentation](../03_Architecture/ARCHITECTURE.md)
