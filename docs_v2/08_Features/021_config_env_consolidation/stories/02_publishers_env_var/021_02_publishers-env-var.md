# Story: Publishers Environment Variable

**Feature ID:** 021  
**Story ID:** 021-02  
**Name:** publishers-env-var  
**Status:** Proposed  
**Date:** 2025-12-22  
**Parent Feature:** 021_config_env_consolidation

## Summary

Implement `PUBLISHERS` JSON array parsing and publisher instantiation. This replaces the current INI-based toggle system (`telegram = true`, `fetlife = true`) with an explicit array of publisher configurations.

## Scope

- Parse `PUBLISHERS` environment variable as JSON array
- Create `TelegramConfig` for entries with `type: "telegram"`
- Create `EmailConfig` for entries with `type: "fetlife"` (with recipient, caption_target, subject_mode)
- Create `InstagramConfig` for entries with `type: "instagram"`
- Derive `PlatformsConfig` enabled flags from presence in array
- Implement precedence: `PUBLISHERS` env var takes priority over INI `[Content]` toggles

## Out of Scope

- Email server configuration (that's Story 03)
- Storage paths (that's Story 04)
- Deprecation warnings (that's Story 06)

## Acceptance Criteria

- Given `PUBLISHERS='[{"type": "telegram", "channel_id": "-100"}]'` and `TELEGRAM_BOT_TOKEN=123`, when config loads, then `TelegramConfig` is created using the token from env and `platforms.telegram_enabled` is `True`.
- Given `PUBLISHERS='[{"type": "fetlife", "recipient": "x@upload.fetlife.com", "caption_target": "subject", "subject_mode": "normal"}]'`, when config loads, then `EmailConfig` is created with those values and `platforms.email_enabled` is `True`.
- Given `PUBLISHERS='[]'` (empty array), when config loads, then no publishers are enabled.
- Given both `PUBLISHERS` env var and INI `[Content] telegram = true`, when config loads, then `PUBLISHERS` takes precedence.
- Given `PUBLISHERS` is not set, when config loads, then fallback to INI-based toggles occurs.
- Given `PUBLISHERS` contains an unknown type, when config loads, then a warning is logged and that entry is skipped.

## Technical Notes

Publisher type mapping:
- `telegram` → `TelegramConfig` + `TelegramPublisher`
- `fetlife` → `EmailConfig` + `EmailPublisher`
- `instagram` → `InstagramConfig` + `InstagramPublisher`

FetLife entries must reference `EMAIL_SERVER` for smtp/sender/password (Story 03 dependency at runtime, but this story can mock/stub that).

## Dependencies

- Story 01: JSON Parser Infrastructure (for `_parse_json_env`)
- Story 03: Email Server (FetLife publisher needs EMAIL_SERVER settings and EMAIL_PASSWORD; implement 03 first or in parallel)

