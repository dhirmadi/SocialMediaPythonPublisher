<!-- docs_v2/08_Features/012_central-config-i18n-text.md -->

# Centralized Configuration & Internationalizable Text — Shipped Feature

**Feature ID:** 012  
**Name:** central-config-i18n-text  
**Status:** Shipped  
**Date:** 2025-11-22  
**Author:** Architecture Team  

---

## Summary

This feature introduces a clear configuration model that separates **secrets**, **dynamic configuration**, and **static text/rules** for Publisher V2.  
It adds a small, versioned **static configuration layer** for AI prompts, platform limits, service limits, preview text, and web UI text, while preserving all existing behavior by default when static config is not customized.

---

## Goals & Non-Goals

### Goals

- Clearly distinguish:
  - **Secrets** — loaded only from environment (`.env`), never stored in repo.
  - **Dynamic variables** — tunable behavior flags and per-environment settings from env + INI.
  - **Static text/rules** — prompts, labels, limits, and rules stored in versioned config files.
- Centralize AI prompts and platform rules in static YAML so they can be tuned without code changes.
- Extract key web UI and preview-mode strings into language-aware config (English defaults).
- Keep CLI and web behavior **backward-compatible** when static config files are absent or left at defaults.

### Non-Goals

- No changes to CLI flags or web API shapes.
- No runtime locale negotiation or language switcher.
- No remote configuration service or runtime reload.
- No attempt to move every minor log/debug string into static config.

---

## User Value

- **Operators / DevOps**
  - Gain a documented configuration model with a single place to see all dynamic env + INI variables.
  - Can adjust AI prompts, caption limits, hashtag rules, and image cache TTL without code changes.
- **Developers**
  - Can tune AI prompts and platform rules via YAML in `publisher_v2/config/static`, reducing iteration cost.
  - Avoid scattering feature toggles and limits across modules; configuration access is explicit and typed.
- **Future translators / content editors**
  - Have a central, language-aware file for web UI text (`web_ui_text.en.yaml`) and preview labels (`preview_text.yaml`), enabling future i18n work.

---

## Technical Overview

### New Static Config Layer

**Module:** `publisher_v2.config.static_loader`

- Provides typed Pydantic models:
  - `AIPromptsConfig` (vision, caption, sd_caption prompts)
  - `PlatformLimitsConfig` (per-platform caption lengths, hashtag limits, resize widths)
  - `PreviewTextConfig` (preview-mode headings and key messages)
  - `WebUITextConfig` (web UI strings for titles, buttons, panels, statuses)
  - `ServiceLimitsConfig` (AI rate limit, Instagram delay range, web cache TTL, SMTP timeout placeholder)
  - `StaticConfig` (root aggregator)
- Loads static YAML files from:
  - `publisher_v2/src/publisher_v2/config/static/ai_prompts.yaml`
  - `publisher_v2/src/publisher_v2/config/static/platform_limits.yaml`
  - `publisher_v2/src/publisher_v2/config/static/preview_text.yaml`
  - `publisher_v2/src/publisher_v2/config/static/web_ui_text.en.yaml`
  - `publisher_v2/src/publisher_v2/config/static/service_limits.yaml`
- Provides:
  - `load_static_config(base_dir: str | None = None) -> StaticConfig`
  - `@lru_cache(maxsize=1) get_static_config() -> StaticConfig`
- Behavior:
  - If a YAML file is missing or malformed, the loader logs a warning and falls back to model defaults.
  - Defaults mirror current behavior (English text and numeric limits), so absence of static config is safe.
  - `PV2_STATIC_CONFIG_DIR` can override the directory for deployment-specific YAMLs.

### AI Prompts

- **Vision analysis (`VisionAnalyzerOpenAI`)**
  - System and user prompts are now derived from `get_static_config().ai_prompts.vision` with:
    - Fallback to existing hard-coded prompts when static entries are absent.
  - JSON schema and key set remain unchanged; only the text source is configurable.
- **Caption generation (`CaptionGeneratorOpenAI`)**
  - System and role prompts are initialized from `OpenAIConfig` as before, then optionally overridden by:
    - `get_static_config().ai_prompts.caption.system`
    - `get_static_config().ai_prompts.caption.role`
- **SD-caption single-call prompts**
  - SD caption system and role prompts can be overridden via `ai_prompts.sd_caption.system` and `.role`.
  - Fallback behavior remains identical (using caption prompts and existing hard-coded SD-caption instructions).

### Platform Limits

- **Static config:** `platform_limits.yaml` with per-platform `max_caption_length`, `max_hashtags`, and `resize_width_px`.
- **Usage in `utils.captions.format_caption`:**
  - Reads limits from `get_static_config().platform_limits` and falls back to the legacy `_MAX_LEN` dict.
  - Instagram hashtag limiting now uses `instagram.max_hashtags` (default 30) instead of a hard-coded number.
  - Email/FetLife caption length (default 240) and generic lengths match previous defaults.
- Preview hints in `utils.preview.print_platform_preview` continue to describe resize widths (1080/1280) which align with static defaults and can be tuned via YAML if future changes are needed.

### Web UI Text

- **Static config:** `web_ui_text.en.yaml` contains:
  - Page title, header title
  - Button labels (Next, Admin, Logout, Analyze & caption, Publish, Keep, Remove)
  - Panel titles (Caption, Administration, Activity)
  - Placeholders (e.g., "No image loaded yet.")
  - Initial status strings (e.g., "Ready.", "Admin mode: off/on")
  - Admin dialog text (title, description, password placeholder)
- **FastAPI app (`web.app.index`)**
  - Now passes `web_ui_text=get_static_config().web_ui_text.values` into the Jinja template.
- **Template (`web/templates/index.html`)**
  - Uses Jinja to render titles, headings, button labels, and initial placeholders from `web_ui_text`, with English literals as fallbacks.
  - Exposes `window.WEB_UI_TEXT` for future client-side usage.
  - No changes to endpoint contracts or admin-mode behavior; only the text source changed.

### Preview Mode Text

- **Static config:** `preview_text.yaml` defines:
  - Section headers for preview: preview mode banner, image selected, vision analysis, caption generation, publishing preview, email confirmation, configuration, preview footer.
  - Key messages: "No caption yet.", "Analysis skipped …", "Publish feature disabled …".
- **Usage in `utils.preview`**
  - `print_preview_header`, `print_vision_analysis`, `print_caption`, `print_platform_preview`, `print_email_confirmation_preview`, `print_config_summary`, and `print_preview_footer` now pull headers/messages from `get_static_config().preview_text`, preserving current wording by default.
  - Emojis, box drawing characters, and layout are unchanged to keep UX stable.

### Service Limits

- **Static config:** `service_limits.yaml` defines:
  - `ai.rate_per_minute` (default 20 requests per minute).
  - `instagram.delay_min_seconds` / `delay_max_seconds` (default 1–3 seconds).
  - `web.image_cache_ttl_seconds` (default 30.0 seconds).
  - `smtp.timeout_seconds` (reserved for future use).
- **Usage:**
  - `AIService` now reads `service_limits.ai.rate_per_minute` and supports an `AI_RATE_PER_MINUTE` env override.
  - `InstagramPublisher` uses `service_limits.instagram` for `client.delay_range`, preserving the 1–3 second default series.
  - `WebImageService` reads `service_limits.web.image_cache_ttl_seconds` for its image cache TTL, with an optional env override `WEB_IMAGE_CACHE_TTL_SECONDS`.
  - Existing retry policies (tenacity) remain unchanged; moving them into static config is left for future work.

---

## Implementation Details

- **New files**
  - `publisher_v2/src/publisher_v2/config/static_loader.py`
  - `publisher_v2/src/publisher_v2/config/static/ai_prompts.yaml`
  - `publisher_v2/src/publisher_v2/config/static/platform_limits.yaml`
  - `publisher_v2/src/publisher_v2/config/static/preview_text.yaml`
  - `publisher_v2/src/publisher_v2/config/static/web_ui_text.en.yaml`
  - `publisher_v2/src/publisher_v2/config/static/service_limits.yaml`
  - `publisher_v2/tests/test_static_config_loader.py`
  - `publisher_v2/tests/test_captions_platform_limits_static.py`
  - `publisher_v2/tests/test_preview_text_static.py`
  - `publisher_v2/tests/test_service_limits_static.py`
- **Modified key files**
  - `publisher_v2/services/ai.py` — static prompt overrides and AI rate limit via `ServiceLimitsConfig`.
  - `publisher_v2/utils/captions.py` — platform limits and Instagram hashtag cap from `PlatformLimitsConfig`.
  - `publisher_v2/utils/preview.py` — preview headings and key messages from `PreviewTextConfig`.
  - `publisher_v2/web/app.py` and `publisher_v2/web/templates/index.html` — web UI text from `WebUITextConfig`.
  - `publisher_v2/web/service.py` — web image cache TTL from `ServiceLimitsConfig` with env override.
  - `publisher_v2/services/publishers/instagram.py` — delay range from `ServiceLimitsConfig.instagram`.
  - `pyproject.toml` — added `PyYAML` dependency for YAML parsing.

All changes are scoped to V2 modules and do not touch archived V1 code or CLI argument parsing.

---

## Testing

- **New tests**
  - `test_static_config_loader.py`
    - Validates that packaged defaults load correctly.
    - Ensures an empty directory via `PV2_STATIC_CONFIG_DIR` still yields sane defaults.
  - `test_captions_platform_limits_static.py`
    - Confirms Instagram captions respect length and hashtag caps defined in static config.
    - Verifies email/FetLife caption sanitization remains correct.
  - `test_preview_text_static.py`
    - Asserts preview header and footer use the configured default text.
  - `test_service_limits_static.py`
    - Checks that `AIService` uses the default rate limit.
    - Verifies Instagram publisher delay range defaults to 1–3 seconds via static limits.
- **Existing tests**
  - Full pytest suite (`uv run pytest -q`) passes unchanged:
    - All 210 tests pass, including AI, preview, sidecar, web, and workflow tests.
  - Web integration tests confirm that `/` still renders and that admin visibility behavior is unchanged.

---

## Configuration & Operations

- **Secrets (unchanged; env only)**
  - `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`
  - `OPENAI_API_KEY`
  - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHANNEL_ID`
  - `INSTA_PASSWORD`, `EMAIL_PASSWORD`
  - `WEB_AUTH_TOKEN`, `WEB_AUTH_USER`, `WEB_AUTH_PASS`, `web_admin_pw`
- **Dynamic variables (env + INI; unchanged semantics)**
  - Feature flags: `FEATURE_ANALYZE_CAPTION`, `FEATURE_PUBLISH`, `FEATURE_KEEP_CURATE`, `FEATURE_REMOVE_CURATE`, `AUTO_VIEW`
  - INI-based configuration under `[Dropbox]`, `[Content]`, `[Email]`, `[openAI]`, `[CaptionFile]`, etc.
- **Static text/rules (new, non-secret)**
  - AI prompts: `ai_prompts.yaml`
  - Platform limits: `platform_limits.yaml`
  - Web UI strings: `web_ui_text.en.yaml`
  - Preview text: `preview_text.yaml`
  - Service limits: `service_limits.yaml`
- **Optional env-based overrides for new static limits**
  - `PV2_STATIC_CONFIG_DIR` — override directory for static YAML files.
  - `AI_RATE_PER_MINUTE` — override AI rate limiter throughput.
  - `WEB_IMAGE_CACHE_TTL_SECONDS` — override web image cache TTL.

Refer to `docs_v2/05_Configuration/CONFIGURATION.md` for the authoritative, tabular listing of dynamic variables and secrets, now updated to reference the static config layer.

---

## Rollout Notes

- Static config files ship with **defaults that match existing behavior**, so upgrading does not require any operator action.
- Operators can gradually introduce custom static config by:
  - Copying the defaults from `publisher_v2/config/static/`.
  - Adjusting prompts, limits, and text as needed.
  - Pointing `PV2_STATIC_CONFIG_DIR` at a deployment-specific directory if overriding the packaged defaults.
- Rollback is straightforward:
  - Revert code and static YAML changes, or remove/ignore custom static config.
  - Because defaults preserve prior behavior, no data migration is required.

---

## Artifacts & Documentation

### Feature 012 Documentation
- **Feature Request:** `docs_v2/08_Features/08_01_Feature_Request/012_central-config-i18n-text.md`
- **Feature Design:** `docs_v2/08_Features/08_02_Feature_Design/012_central-config-i18n-text_design.md`
- **Plan:** `docs_v2/08_Features/08_03_Feature_plan/012_central-config-i18n-text_plan.yaml`
- **Shipped Summary (this file):** `docs_v2/08_Features/012_central-config-i18n-text.md`
- **i18n Activation Guide:** `docs_v2/08_Features/012_i18n_activation_summary.md`
- **Documentation Update Summary:** `docs_v2/08_Features/012_DOCUMENTATION_UPDATE_SUMMARY.md`
- **Implementation Review:** `docs_v2/09_Reviews/20251122_fullreview.md`

### Core Documentation Updated
- `docs_v2/05_Configuration/CONFIGURATION.md` → v2.6 (three-layer model, static config reference)
- `docs_v2/03_Architecture/ARCHITECTURE.md` → v2.6 (static config architecture)
- `README.md` → Updated configuration section
- `CHANGELOG.md` → v2.6.0 release notes


