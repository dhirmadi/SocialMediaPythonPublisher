# PUB-012: Centralized Configuration & Internationalizable Text

| Field | Value |
|-------|-------|
| **ID** | PUB-012 |
| **Category** | Config |
| **Priority** | INF |
| **Effort** | M |
| **Status** | Done |
| **Dependencies** | — |

## Problem

Configuration and text are spread across multiple sources: secrets and some toggles in `.env`, runtime behavior in INI files, and AI prompts, platform limits, preview labels, and web UI strings hard-coded in Python and HTML. This leads to unclear modeling of secrets vs. non-secrets, scattered dynamic toggles, AI prompts and platform rules requiring code changes to tune, English-only user-facing text, and brittle platform limits that need code updates when platforms change.

## Desired Outcome

A clear configuration model separating **secrets** (env only), **dynamic variables** (env + INI), and **static text/rules** (versioned static config). AI prompts, platform limits, and service limits centralized in structured static config. Web UI and preview-mode strings extracted into language-aware static config with English as default. All existing behavior preserved when static config is missing or at defaults. System prepared for future i18n without further code changes.

## Scope

- Static config layer: `publisher_v2/config/static/` with typed loaders and safe defaults
- Static config files: `ai_prompts.yaml`, `platform_limits.yaml`, `web_ui_text.en.yaml`, `preview_text.yaml`, `service_limits.yaml`
- Pydantic models: `AIPromptsConfig`, `PlatformLimitsConfig`, `PreviewTextConfig`, `WebUITextConfig`, `ServiceLimitsConfig`, `StaticConfig`
- `load_static_config()` and `get_static_config()`; fallback to in-code defaults when files missing
- Env override: `PV2_STATIC_CONFIG_DIR`; optional `AI_RATE_PER_MINUTE`, `WEB_IMAGE_CACHE_TTL_SECONDS`

## Acceptance Criteria

- AC1: Given a fresh deployment with no new static config files, CLI and web behavior match current behavior (backward compatible)
- AC2: Given `ai_prompts` static config defines new prompts, workflows use those instead of hard-coded prompts in `services/ai.py`
- AC3: Given `platform_limits` static config defines caption length and hashtag limits per platform, captions respect those limits
- AC4: Given `web_ui_text` static config contains English text, web UI strings come from config with existing defaults when entries missing
- AC5: Given `preview_text` static config is present, preview mode headings and labels come from config
- AC6: Given `service_limits` static config defines rate limits, retries, timeouts, web cache TTL, services apply those with documented env overrides
- AC7: Given documentation updated, `CONFIGURATION.md` clearly distinguishes secrets, dynamic, and static variables

## Implementation Notes

- New module: `publisher_v2.config.static_loader`; PyYAML dependency
- AI services, captions, preview, web app, Instagram publisher, and WebImageService read from static config
- Static config read once at startup; merged with in-code defaults; log warnings on missing/invalid files
- No changes to required env vars or INI semantics; no runtime locale negotiation or remote config

## Related

- [Original feature doc](../../08_Epics/004_deployment_ops_modernization/012_central_config_i18n_text/012_feature.md) — full historical detail
