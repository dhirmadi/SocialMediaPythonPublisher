# Story Summary: Email Server Environment Variable

**Feature ID:** 021  
**Story ID:** 021-03  
**Status:** Shipped  
**Date Completed:** 2025-12-23

## Summary

Implemented the `_load_email_server_from_env()` function to parse the `EMAIL_SERVER` JSON environment variable for SMTP configuration. This provides a clean, env-first way to configure email server settings without embedding secrets.

## Files Changed

### Source Files
- `publisher_v2/src/publisher_v2/config/loader.py` — Added `_load_email_server_from_env()` function that:
  - Parses EMAIL_SERVER JSON object
  - Validates required `sender` field
  - Provides defaults for `smtp_server` ("smtp.gmail.com") and `smtp_port` (587)
  - Validates smtp_port is an integer
  - Returns None when env var is unset/empty
  - Propagates ConfigurationError on invalid JSON

### Test Files
- `publisher_v2/tests/config/test_loader_env_helpers.py` — Added `TestLoadEmailServerFromEnv` class with 7 tests covering:
  - Returns None when unset
  - Returns None when empty
  - Parses minimal config (sender only)
  - Parses full config (all fields)
  - Raises when sender missing
  - Raises when smtp_port not integer
  - Raises on invalid JSON

## Test Results

- Tests: 7 passed, 0 failed
- Coverage: Full coverage of new function

## Acceptance Criteria Status

- [x] AC1: Given valid EMAIL_SERVER JSON with sender, smtp_server, smtp_port, parser returns dict with all fields
- [x] AC2: Given EMAIL_SERVER with only sender, parser uses defaults for smtp_server and smtp_port
- [x] AC3: Given EMAIL_SERVER missing sender, parser raises ConfigurationError
- [x] AC4: Given EMAIL_SERVER with non-integer smtp_port, parser raises ConfigurationError
- [x] AC5: Secrets (EMAIL_PASSWORD) remain as separate flat env var, not in JSON

## Follow-up Items

- None — ready for integration in Story 06

## Artifacts

- Story Definition: 021_03_email-server-env-var.md
- Story Design: 021_03_design.md
- Story Plan: 021_03_plan.yaml

