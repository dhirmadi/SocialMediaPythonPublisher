# PUB-021: Configuration Environment Variable Consolidation

| Field | Value |
|-------|-------|
| **ID** | PUB-021 |
| **Category** | Config |
| **Priority** | INF |
| **Effort** | L |
| **Status** | Done |
| **Dependencies** | PUB-012 |

## Problem

Configuration is spread across `.env` (secrets, some infrastructure) and `configfiles/*.ini` (application settings). This split creates cognitive overhead, inconsistent patterns, redundant toggles, and migration complexity for the upcoming Orchestrator API. Heroku and container deployments prefer environment variables over mounted config files.

## Desired Outcome

Consolidate all configuration into environment variables. Keep secrets as separate env vars (auditable, rotatable); use JSON for non-secret groupings (`STORAGE_PATHS`, `OPENAI_SETTINGS`, `PUBLISHERS`, etc.). Structure publishers as a JSON array without embedding secrets. Remove redundant toggle variables by deriving enabled publishers from the array. Align folder path semantics with Orchestrator API (absolute/root paths). Maintain backward compatibility via fallback logic.

## Scope

- New JSON env vars: `PUBLISHERS`, `EMAIL_SERVER`, `STORAGE_PATHS`, `OPENAI_SETTINGS`, `CAPTIONFILE_SETTINGS`, `CONFIRMATION_SETTINGS`, `CONTENT_SETTINGS`
- Precedence: new JSON env vars > old individual env vars > INI sections
- Deprecation warning when INI is used
- Full env template: `dotenv.v2.example`
- Heroku pipeline migration runbook (Story 021-07)

## Acceptance Criteria

- AC1: Given `PUBLISHERS` contains a Telegram entry, when the app starts, then Telegram is enabled using `TELEGRAM_CHANNEL_ID` and `TELEGRAM_BOT_TOKEN`
- AC2: Given `PUBLISHERS` contains a FetLife entry, when the app starts, then Email publisher is enabled with specified recipient, caption_target, subject_mode
- AC3: Given `PUBLISHERS` is empty or missing, when the app starts, then no publishers are enabled
- AC4: Given old INI exists but `PUBLISHERS` is defined, when the app starts, then `PUBLISHERS` takes precedence
- AC5: Given `PUBLISHERS` contains duplicate `type` entries, when the app starts, then configuration fails fast with clear error
- AC6: Given `EMAIL_SERVER` JSON + `EMAIL_PASSWORD`, when sending emails, then those settings are used
- AC7: Given `STORAGE_PATHS` with absolute paths, when archiving, then full path is used as-is
- AC8: Given `OPENAI_SETTINGS` JSON, when performing AI operations, then those settings are used
- AC9: Given no new env vars, when the app starts with only old INI config, then behavior is identical

## Implementation Notes

- JSON parsing fails fast with clear error messages
- Pydantic models remain internal representation; only loader changes
- Secrets never logged; python-dotenv for local `.env` loading
- Aligns with Orchestrator API contract for Epic 001

## Related

- [Original feature doc](../../08_Epics/004_deployment_ops_modernization/021_config_env_consolidation/021_feature.md) — full historical detail
