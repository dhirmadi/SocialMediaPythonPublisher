# Story Summary: Publishers Environment Variable

**Feature ID:** 021  
**Story ID:** 021-02  
**Status:** Shipped  
**Date Completed:** 2025-12-23

## Summary

Implemented the `_load_publishers_from_env()` function to parse the `PUBLISHERS` JSON array environment variable and create publisher configurations for Telegram, FetLife (Email), and Instagram platforms.

## Files Changed

### Source Files
- `publisher_v2/src/publisher_v2/config/loader.py` — Added `_load_publishers_from_env()` function that:
  - Parses PUBLISHERS JSON array
  - Creates TelegramConfig, InstagramConfig, and EmailConfig objects
  - Validates required fields per publisher type
  - Enforces secrets (TELEGRAM_BOT_TOKEN, EMAIL_PASSWORD, INSTA_PASSWORD) as separate env vars
  - Detects duplicate publisher types
  - Falls back to INI for SMTP settings when EMAIL_SERVER not set
  - Uses CONFIRMATION_SETTINGS from env when available

### Test Files
- `publisher_v2/tests/config/test_loader_env_helpers.py` — Added `TestLoadPublishersFromEnv` class with 15 tests covering:
  - Telegram publisher parsing and validation
  - FetLife publisher with EMAIL_SERVER integration
  - FetLife fallback to INI configuration
  - Instagram publisher parsing
  - Missing secret env var error handling
  - Missing required field error handling
  - Multiple publishers in single array
  - Duplicate type detection
  - Unknown publisher type warning
  - Empty publishers list handling
  - CONFIRMATION_SETTINGS integration

## Test Results

- Tests: 15 passed, 0 failed
- Coverage: Full coverage of new function

## Acceptance Criteria Status

- [x] AC1: Given valid PUBLISHERS JSON with telegram entry and TELEGRAM_BOT_TOKEN set, parser returns TelegramConfig
- [x] AC2: Given valid PUBLISHERS JSON with fetlife entry and EMAIL_PASSWORD set, parser returns EmailConfig
- [x] AC3: Given valid PUBLISHERS JSON with instagram entry and INSTA_PASSWORD set, parser returns InstagramConfig
- [x] AC4: Given PUBLISHERS with duplicate type entries, parser raises ConfigurationError
- [x] AC5: Given PUBLISHERS entry missing required secret env var, parser raises ConfigurationError

## Follow-up Items

- Integration with `load_application_config()` to use PUBLISHERS when set (Story 06 scope)

## Artifacts

- Story Definition: 021_02_publishers-env-var.md
- Story Design: 021_02_design.md
- Story Plan: 021_02_plan.yaml

