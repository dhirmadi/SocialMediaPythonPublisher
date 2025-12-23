# Story: Email Server Environment Variable

**Feature ID:** 021  
**Story ID:** 021-03  
**Name:** email-server-env-var  
**Status:** Proposed  
**Date:** 2025-12-22  
**Parent Feature:** 021_config_env_consolidation

## Summary

Implement `EMAIL_SERVER` JSON parsing for shared SMTP configuration. This consolidates email infrastructure settings that were previously split between `.env` (`EMAIL_PASSWORD`) and INI (`smtp_server`, `smtp_port`, `sender`).

## Scope

- Parse `EMAIL_SERVER` environment variable as JSON object
- Extract: `smtp_server`, `smtp_port`, `sender`
- Password comes from flat `EMAIL_PASSWORD` env var (not `EMAIL_SERVER`)
- Apply to `EmailConfig` when FetLife publisher is enabled
- Implement precedence: `EMAIL_SERVER` > individual env vars (`SMTP_SERVER`, `EMAIL_PASSWORD`) > INI

## Out of Scope

- Publisher array parsing (that's Story 02)
- Confirmation email settings (that's Story 05)

## Acceptance Criteria

- Given `EMAIL_SERVER='{"smtp_server": "smtp.gmail.com", "smtp_port": 587, "sender": "user@gmail.com"}'` and `EMAIL_PASSWORD=secret`, when config loads for FetLife publisher, then those values are used together.
- Given `EMAIL_SERVER` is set and old `SMTP_SERVER` env var exists, when config loads, then `EMAIL_SERVER.smtp_server` takes precedence.
- Given `EMAIL_SERVER` is not set, when config loads, then fallback to `SMTP_SERVER`, `EMAIL_PASSWORD` env vars and INI `[Email]` section occurs.
- Given `EMAIL_SERVER` is set but `EMAIL_PASSWORD` is missing, when config loads with a FetLife publisher enabled, then `ConfigurationError` is raised.
- Given `EMAIL_SERVER.smtp_port` is not an integer, when config loads, then `ConfigurationError` is raised with clear message.

## Technical Notes

Default values:
- `smtp_server`: `"smtp.gmail.com"`
- `smtp_port`: `587`

Required fields:
- `sender` (email address)
 - `password` (app password or SMTP password) comes from `EMAIL_PASSWORD` env var

The `EMAIL_SERVER` provides infrastructure config. Publisher-specific settings (recipient, caption_target, subject_mode) come from `PUBLISHERS` array.

## Dependencies

- Story 01: JSON Parser Infrastructure
- Note: Story 02 consumes EMAIL_SERVER output when building EmailConfig for FetLife publishers.

