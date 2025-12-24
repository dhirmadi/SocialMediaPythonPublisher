<!-- docs_v2/08_Epics/08_01_Feature_Request/016_structured-logging-redaction.md -->

# Structured Logging & Redaction

**ID:** 016  
**Name:** structured-logging-redaction  
**Status:** Shipped  
**Date:** 2025-11-22  
**Author:** Retroactive Documentation  

## Summary
A centralized logging framework that outputs machine-parseable JSON payloads while strictly enforcing the redaction of sensitive secrets (API keys, tokens) to prevent leaks. This forms the foundation for all observability in the system.

## Problem Statement
Standard Python text logging (e.g., `INFO: User logged in`) is hard to parse programmatically and dangerous in a system handling high-value secrets (OpenAI keys, Telegram tokens). A single accidental log of a config object or exception traceback could compromise the user's accounts. Furthermore, without structured fields (like `correlation_id`), debugging concurrent or distributed runs is difficult.

## Goals
- **Safety:** Automatically strip known secret patterns (`sk-...`, `r8_...`, bot tokens) from all log messages before they leave the application.
- **Structure:** Emit logs where the "message" portion is a valid JSON object containing standardized keys (`timestamp`, `level`, `message`) and arbitrary context fields.
- **Consistency:** Provide a single `setup_logging` function used by CLI, Web, and Workers to ensure uniform output format.
- **Parsability:** Enable downstream tools (Datadog, CloudWatch, `jq`) to extract the JSON payload for analysis.

## Non-Goals
- **Log Aggregation Backend:** Setting up an ELK stack, Splunk, or Datadog instance is out of scope; we only provide the *output format* suitable for ingestion.
- **Pure JSON Output:** The current implementation wraps the JSON object in a standard Python log header (Timestamp/Level) to maintain compatibility with simple console viewers.
- **Audit Logging:** While these logs help with auditing, this is not a cryptographic audit trail system.

## Users & Stakeholders
- **Security Auditor:** Who verifies that secrets are not leaking into persistent logs.
- **Operator/DevOps:** Who uses `grep` or `jq` to inspect the JSON payloads.
- **Developer:** Who needs to attach context (e.g., `duration_ms=150`) to logs without messy string formatting.

## User Stories
- As a security auditor, I want to ensure that even if an exception dumps a configuration object, the API keys within it are redacted.
- As an operator, I want logs where the payload is JSON so I can easily parse timings and IDs.
- As a developer, I want to be able to call `log_json(logger, INFO, "event", user_id="123")` and have it produce a structured log entry.

## Acceptance Criteria (BDD-style)
- **Given** a log message containing an OpenAI key (`sk-abc123...`), **when** it is emitted, **then** the output must contain `[OPENAI_KEY_REDACTED]` instead of the key.
- **Given** a call to `log_json` with extra kwargs `{"retry_count": 3}`, **when** the log is written, **then** the JSON object must contain a key `"retry_count": 3`.
- **Given** the application startup, **when** `setup_logging` is called, **then** the root logger must be configured to output to stdout.

## Technical Constraints & Assumptions
- **Format:** Hybrid (Text Header + JSON Payload).
    - Example: `2025-11-22 10:00:00 - logger - INFO - {"message": "...", "timestamp": "..."}`
- **Performance:** Redaction uses compiled Regex; overhead must be minimal for typical log volumes.
- **Compatibility:** Must integrate with Python's standard `logging` module.

## Dependencies & Integrations
- **Standard Lib:** `logging`, `json`, `re`.
- **Feature 007:** This feature provides the mechanism used by "Cross-Cutting Performance Observability".

## Risks & Mitigations
- **Risk:** Regex misses a novel secret format.  
  **Mitigation:** Regular review of regex patterns; strict scoping of secrets to environment variables (not hardcoded).
- **Risk:** JSON serialization failure for complex objects.  
  **Mitigation:** `log_json` should handle non-serializable objects gracefully (e.g., `str()`) or developers must pass only serializable primitives.
