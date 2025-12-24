<!-- docs_v2/08_Epics/08_01_Feature_Request/012_central-config-i18n-text.md -->

# Centralized Configuration & Internationalizable Text

**ID:** 012  
**Name:** central-config-i18n-text  
**Status:** Shipped  
**Date:** 2025-11-22  
**Author:** User Request  

## Summary
The application currently mixes secrets, dynamic behavior flags, and static text across environment variables, INI files, Python code, and the web UI template. This feature introduces a clear configuration model that separates secrets, dynamic runtime configuration, and static text/rules into dedicated layers, with a new static config layer for AI prompts, platform rules, service limits, preview text, and web UI text. The goal is to centralize configuration, make behavior and text tunable without code changes, and prepare the system for future internationalization while preserving all existing behavior by default.

## Problem Statement
Configuration and text are currently spread across multiple sources:

- Secrets and some feature toggles are stored in `.env` / process environment  
- Runtime behavior and platform enablement are configured via INI files under `configfiles/`  
- AI prompts, platform limits, preview mode labels, and web UI strings are hard-coded in Python and HTML

This leads to several issues:

- Secrets vs non-secrets are not clearly modeled, increasing the risk of accidentally committing sensitive data  
- Dynamic behavioral toggles are scattered between `.env`, INI, and code, making it hard to understand and change runtime behavior safely  
- AI prompts and platform rules are hard-coded, so tuning them requires code changes and redeploys  
- All user-facing text is English-only and lives in code/HTML, making internationalization and content updates difficult  
- Platform limits (caption length, hashtag limits, resize widths) are brittle and need code updates when platforms change

## Goals
- Clearly separate and document three classes of variables:
  - **Secrets**: only in environment (`.env`), never in repo-tracked config files
  - **Dynamic variables**: feature toggles and behavior flags, adjustable per environment via env + INI
  - **Static variables**: prompts, platform rules, service limits, and user-facing text stored in versioned static config
- Centralize AI prompts, platform limits, and service limits into structured static config so they can be tuned without code changes.
- Extract web UI and preview-mode user-facing strings into language-aware static config, with English as the default.
- Preserve all existing runtime behavior and configuration entry points (env + INI) when static config files are missing or at defaults.
- Prepare the system for future i18n by making it possible to add new language files without further code changes.

## Non-Goals
- Changing the overall runtime workflow or orchestrator behavior beyond configuration lookup and text sourcing.
- Altering the set of required environment variables or INI sections/keys.
- Implementing a full internationalization system (no locale switcher, no runtime language negotiation).
- Introducing a remote configuration service or dynamic config reloading at runtime.
- Changing the semantics of existing feature flags, publisher enablement flags, or preview/dry-run behavior.

## Users & Stakeholders
- **Operators / DevOps**: Need a clear, documented configuration story to safely adjust behavior and limits per environment without risking secrets or code changes.
- **Developers**: Want to tune AI prompts, platform rules, and service limits in a structured way, and avoid scattering toggles across the codebase.
- **Content reviewers / admins**: Benefit from consistent web UI and preview output that can later be localized.
- **Future translators / localization contributors**: Need a central place to provide non-English text without modifying Python or HTML.

## User Stories
- As an operator, I want a single reference document that lists all dynamic configuration (env + INI), so I can understand what knobs exist and how to change them safely.
- As a developer, I want AI prompts and platform rules defined in versioned config files, so I can iterate on them without editing Python modules.
- As an operator, I want platform-specific caption length and hashtag limits to live in config, so when a platform changes its limits I can adjust them without a new release.
- As a future translator, I want all web UI and preview text in language-specific config files, so I can provide another language without touching code.
- As an operator, I want static service limits (rate limits, retries, timeouts) in config with environment overrides, so I can tune them per deployment.
- As a developer, I want default behavior to remain unchanged when static config files are missing or incomplete, so rollouts are safe and backward-compatible.

## Acceptance Criteria (BDD-style)
- Given a fresh deployment with no new static config files present, when the CLI and web workflows run, then behavior and user-visible text must match current behavior (backward compatible).
- Given the `ai_prompts` static config defines new prompts for vision analysis, captioning, and SD captioning, when workflows run, then those prompts must be used instead of hard-coded prompts in `services/ai.py` without code changes.
- Given the `platform_limits` static config defines caption length and hashtag limits for each platform, when captions are formatted and published, then those limits must be respected and match the previous defaults unless overridden.
- Given the `web_ui_text` static config contains English text, when the web UI is rendered, then user-facing strings must come from that config while preserving the existing English defaults when config entries are missing.
- Given the `preview_text` static config is present, when preview mode is used, then headings and labels in CLI output must come from the config while preserving current wording as defaults.
- Given the `service_limits` static config defines OpenAI rate limits, retry parameters, SMTP timeout, Instagram delay range, and web cache TTL, when services run, then those limits must be applied, with documented environment variable overrides where supported.
- Given documentation is updated, when an operator reads `docs_v2/05_Configuration/CONFIGURATION.md`, then they can clearly see which variables are secrets, which are dynamic, and which are static text/rules.

## UX / Content Requirements
- Web UI must continue to render English text even if static text config is missing or partial.
- Preview mode output must remain readable and match current structure, while allowing labels/headings to be sourced from config.
- Error and log messages related to configuration must clearly distinguish secrets, dynamic config, and static config.
- Static config files should be human-readable, diff-friendly (YAML/JSON), and versioned under `docs_v2` or `publisher_v2/config/static`.

## Technical Requirements
- Introduce a static config layer (e.g., `publisher_v2/config/static/`) with typed loaders and safe defaults.
- Support at least the following static config files: `ai_prompts`, `platform_limits`, `web_ui_text.<locale>`, `preview_text`, `service_limits`.
- Ensure static config is read once at startup and merged with in-code defaults to avoid hard failures when keys are missing.
- Preserve existing env + INI configuration loading for secrets and dynamic variables; do not change required keys or semantics.
- Expose dynamic and static config structures in a way that can be exercised by tests (unit + e2e) without external dependencies.

## Dependencies
- Existing configuration loader and schema: `publisher_v2.config.loader`, `publisher_v2.config.schema`.
- AI services: `publisher_v2.services.ai.AIService`, `VisionAnalyzerOpenAI`, `CaptionGeneratorOpenAI`.
- Web UI and templates: `publisher_v2.web.app`, `publisher_v2.web.templates.index.html`.
- Preview utilities: `publisher_v2.utils.preview`.
- Existing feature toggle and platform enablement behavior.

## Risks & Mitigations
- **Risk:** Overcomplicating configuration and making it harder to understand.  
  **Mitigation:** Keep the static config layer small and focused, with clear defaults and documentation; avoid introducing deep hierarchies or unnecessary abstractions.
- **Risk:** Breaking existing behavior if static config loading fails.  
  **Mitigation:** Always fall back to safe in-code defaults when static config is missing or invalid; log warnings instead of failing hard.
- **Risk:** Leaking secrets into new config files by accident.  
  **Mitigation:** Clearly document which variables are secrets and restrict static config files to non-secret prompts, text, and numeric limits only.
- **Risk:** Making future i18n harder by baking in assumptions.  
  **Mitigation:** Design static text config with locale support from the start (e.g., `web_ui_text.en.yaml`), even if only English is implemented initially.

## Open Questions
- How should locales be selected in the future (env var, config, HTTP negotiation), and where should that decision live? (Out of scope for this feature; assume a single locale for now.)
- Should static config support environment-based layering (e.g., base file + per-env override) or rely on full-file replacement per deployment?
- To what extent should platform rules (like caption formatting or hashtag normalization) be moved into config vs. remaining in code?


