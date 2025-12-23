# Configuration Environment Variable Consolidation

**ID:** 021  
**Name:** config-env-consolidation  
**Status:** Shipped  
**Date:** 2025-12-22  
**Author:** Product / Platform

## Summary

Consolidate the split configuration between `.env` file and `configfiles/*.ini` files into a unified `.env`-based structure. This technical debt reduction prepares the codebase for the upcoming Orchestrator API integration (Epic 001), where most configuration values will be database-driven and exposed via runtime config endpoints.

## Problem Statement

Configuration is currently spread across two locations:

1. **`.env` file** — Secrets (passwords, API keys, tokens) and some infrastructure settings
2. **`configfiles/*.ini`** — Application settings (publishers, folders, AI prompts, metadata options)

This split creates several problems:

- **Cognitive overhead**: Developers must check two files to understand the full configuration
- **Inconsistent patterns**: Some related settings are in different files (e.g., `EMAIL_PASSWORD` in `.env` but `smtp_server` in INI)
- **Redundant toggles**: Publisher enable/disable flags (`telegram = true`, `fetlife = true`) exist alongside the presence/absence of credentials
- **Migration complexity**: Transitioning to Orchestrator API-driven config requires a clear, flat structure that maps to the API contract
- **Deployment friction**: Heroku and container deployments prefer environment variables over mounted config files

## Goals

- Consolidate all configuration into environment variables (Heroku config vars / `.env`)
- **Keep secrets as separate env vars** (auditable + rotatable); use JSON only for non-secret groupings
- Structure non-secret groupings as JSON (`STORAGE_PATHS`, `OPENAI_SETTINGS`, etc.)
- Structure publishers as a JSON array **without embedding secrets** (`PUBLISHERS`)
- Remove redundant toggle variables by deriving enabled publishers from the `PUBLISHERS` array
- Align folder path semantics with the Orchestrator API contract (absolute/root paths)
- Maintain backward compatibility during transition via fallback logic
- Preserve all existing functionality with no behavioral changes

## Non-Goals

- Implementing the actual Orchestrator API integration (that's Epic 001)
- Changing the INI file format itself (just migrating away from it)
- Adding new publishers or features
- Changing the web UI or CLI behavior

## Users & Stakeholders

- **Primary users**: Operators deploying the Publisher V2 application
- **Developers**: Team maintaining the codebase
- **Future**: Orchestrator API integration will consume this cleaner structure

## User Stories

- As an operator, I want all configuration in one `.env` file, so that I don't need to manage both `.env` and INI files.
- As a developer, I want publishers defined as an array, so that adding new publishers is consistent and the enabled state is implicit.
- As an operator preparing for multi-tenant, I want the config structure to match the Orchestrator API shape, so that migration is straightforward.

## Acceptance Criteria (BDD-style)

### Publishers Configuration

- Given the `PUBLISHERS` environment variable contains a JSON array with a Telegram publisher entry, when the application starts, then the Telegram publisher is enabled using `TELEGRAM_CHANNEL_ID` and the secret `TELEGRAM_BOT_TOKEN` (flat env var).
- Given the `PUBLISHERS` environment variable contains a JSON array with a FetLife publisher entry, when the application starts, then the Email publisher is enabled with the specified recipient, caption_target, and subject_mode.
- Given the `PUBLISHERS` environment variable is empty or missing, when the application starts, then no publishers are enabled.
- Given the old INI-based `[Content] telegram = true` setting exists but `PUBLISHERS` is defined, when the application starts, then `PUBLISHERS` takes precedence.
- Given the `PUBLISHERS` environment variable contains two entries with the same `type`, when the application starts, then configuration fails fast with a clear error stating duplicate publisher types are not allowed.

### Email Server Configuration

- Given the `EMAIL_SERVER` environment variable contains JSON with smtp_server, smtp_port, and sender, and `EMAIL_PASSWORD` is set as a separate env var, when sending emails, then those settings are used.
- Given both old `.env` variables (`SMTP_SERVER`, `EMAIL_PASSWORD`) and new `EMAIL_SERVER` exist, when loading config, then `EMAIL_SERVER` takes precedence.

### Storage Configuration

- Given the `STORAGE_PATHS` environment variable contains JSON with root, archive, keep, and remove paths, when the application accesses Dropbox, then those paths are used.
- Given STORAGE_PATHS provides absolute paths (e.g., `/Photos/2025/archive`), when archiving files, then the full path is used as-is without additional prefixing.

### AI Configuration

- Given the `OPENAI_SETTINGS` environment variable contains JSON with vision_model, caption_model, system_prompt, and role_prompt, when performing AI operations, then those settings are used.
- Given both INI `[openAI]` section and `OPENAI_SETTINGS` exist, when loading config, then `OPENAI_SETTINGS` takes precedence.

### CaptionFile Configuration

- Given the `CAPTIONFILE_SETTINGS` environment variable contains JSON with extended_metadata_enabled and artist_alias, when generating caption files, then those settings are used.

### Confirmation/Hashtags Configuration

- Given the `CONFIRMATION_SETTINGS` environment variable contains JSON with confirmation_to_sender, confirmation_tags_count, and confirmation_tags_nature, when sending confirmation emails, then those settings are used.

### Content Core Settings

- Given `CONTENT_SETTINGS` contains JSON with `hashtag_string`, `archive`, and `debug`, when the application starts, then those settings are applied consistently with existing V2 behavior.

### Backward Compatibility

- Given no new environment variables are set, when the application starts with only old INI config, then the application behaves identically to before.

## UX / Content Requirements

- No UI changes required
- CLI behavior unchanged
- Operator documentation must be updated with new `.env` structure and examples

## Technical Constraints & Assumptions

- Environment variables have a size limit (~128KB on most systems); JSON arrays must stay reasonable
- JSON parsing errors must fail fast with clear error messages
- Secrets (passwords, tokens) must never be logged, even in debug mode
- Python 3.11+ assumed (using `json` module for parsing)
- Pydantic models remain the internal representation; only the loader changes

## Dependencies & Integrations

- **Orchestrator API** (future): The new structure aligns with the `config.storage.paths`, `config.features`, and publisher sections from Epic 001
- **Heroku**: Environment variables are the native config mechanism
- **python-dotenv**: Continues to load `.env` files for local development

## Data Model / Schema

### New Environment Variables

```bash
# Secrets (flat, auditable, rotatable)
TELEGRAM_BOT_TOKEN=123:abc
EMAIL_PASSWORD=secret
INSTA_PASSWORD=secret

# Publishers as JSON array (non-secret)
PUBLISHERS='[
  {"type": "telegram", "channel_id": "-100123"},
  {"type": "fetlife", "recipient": "...", "caption_target": "subject", "subject_mode": "normal"}
]'

# Email server (shared by all email-based publishers; non-secret)
EMAIL_SERVER='{"smtp_server": "smtp.gmail.com", "smtp_port": 587, "sender": "user@gmail.com"}'

# Storage paths (absolute paths as per Orchestrator API)
STORAGE_PATHS='{"root": "/Photos/Tati/2025", "archive": "/Photos/Tati/2025/archive", "keep": "/Photos/Tati/2025/approve", "remove": "/Photos/Tati/2025/reject"}'

# OpenAI settings
OPENAI_SETTINGS='{"vision_model": "gpt-4o", "caption_model": "gpt-4o-mini", "system_prompt": "...", "role_prompt": "..."}'

# CaptionFile settings
CAPTIONFILE_SETTINGS='{"extended_metadata_enabled": true, "artist_alias": "Eoel"}'

# Confirmation email settings
CONFIRMATION_SETTINGS='{"confirmation_to_sender": true, "confirmation_tags_count": 5, "confirmation_tags_nature": "..."}'

# Content core settings (missing in v1 design; required for parity)
CONTENT_SETTINGS='{"hashtag_string": "#art #photography", "archive": true, "debug": false}'
```

### Precedence Order

1. New JSON environment variables (highest priority)
2. Old individual environment variables (e.g., `SMTP_SERVER`)
3. INI file sections (lowest priority, backward compatibility)

## Security / Privacy / Compliance

- Secrets remain in `.env` (not committed to git)
- JSON parsing does not introduce new attack vectors
- Password/token values must not appear in logs or error messages
- No change to existing redaction/safe-logging patterns

## Performance & SLOs

- No runtime performance impact (config is loaded once at startup)
- Startup time unchanged (JSON parsing is fast)

## Observability

- **Metrics**: None new required
- **Logs**: Configuration source logged at INFO level (e.g., "Loaded publishers from PUBLISHERS env var")
- **Alerts**: None new required

## Risks & Mitigations

- **Risk**: JSON syntax errors in environment variables cause silent failures  
  **Mitigation**: Fail fast with clear error messages indicating which variable and the parse error

- **Risk**: Operators confused by dual config systems during transition  
  **Mitigation**: Clear documentation, deprecation warnings for INI-based config

- **Risk**: Storage path format mismatch with current relative-path logic  
  **Mitigation**: Careful handling in loader; detect absolute vs relative paths and handle accordingly

## Open Questions

- **Q**: Should we log a deprecation warning when INI-based config is used?  
  **A**: Yes, emit a warning to encourage migration.

- **Q**: How long to maintain backward compatibility with INI files?  
  **A**: Versioned deprecation plan:
  - **v2.7**: introduce env consolidation + deprecation warning when INI is used
  - **v2.8**: INI support deprecated (warning on every startup when used)
  - **v3.0** (orchestrator multi-tenant runtime): remove INI support from deployment path

## Milestones

- **M1**: Design approved, story breakdown complete
- **M2**: New loader implemented with full precedence logic
- **M3**: Tests passing, documentation updated
- **M4**: Deployed to staging, validated with real workloads

## Deployment & Migration Note (Heroku)

When Feature 021 is adopted for the `fetlife` Heroku pipeline, we should stop using the `FETLIFE_INI` config var bootstrap pattern and run **env-first**. See Story 021-07 for the rollout plan and local `.env` migration steps.

## Definition of Done

- [x] New JSON environment variables parsed correctly
- [x] Precedence order implemented and tested
- [x] Backward compatibility with INI files maintained
- [x] Unit tests for all new parsing logic
- [x] Integration tests verify end-to-end behavior
- [x] Documentation updated with new `.env` structure
- [x] Heroku deployment guidance updated so `FETLIFE_INI` is no longer required (pipeline migration story)
- [x] No secrets logged in any configuration path

