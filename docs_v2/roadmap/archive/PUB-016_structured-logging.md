# PUB-016: Structured Logging & Redaction

| Field | Value |
|-------|-------|
| **ID** | PUB-016 |
| **Category** | Observability |
| **Priority** | INF |
| **Effort** | S |
| **Status** | Done |
| **Dependencies** | — |

## Problem

Standard Python text logging is hard to parse programmatically and dangerous in a system handling high-value secrets (OpenAI keys, Telegram tokens). A single accidental log of a config object or exception traceback could compromise accounts. Without structured fields (like `correlation_id`), debugging concurrent or distributed runs is difficult.

## Desired Outcome

A centralized logging framework that outputs machine-parseable JSON payloads while strictly enforcing redaction of sensitive secrets. Automatically strip known secret patterns (`sk-...`, `r8_...`, bot tokens) from all log messages. Emit logs where the message portion is valid JSON with standardized keys (`timestamp`, `level`, `message`) and arbitrary context fields. Single `setup_logging` function used by CLI, Web, and Workers for uniform output.

## Scope

- Hybrid format: Text Header + JSON Payload (e.g., `2025-11-22 10:00:00 - logger - INFO - {"message": "...", "timestamp": "..."}`)
- `log_json(logger, level, "event", **kwargs)` for structured entries
- Compiled regex redaction for minimal overhead
- Integration with Python standard `logging` module

## Acceptance Criteria

- AC1: Given a log message containing an OpenAI key (`sk-abc123...`), when it is emitted, then the output must contain `[OPENAI_KEY_REDACTED]` instead of the key
- AC2: Given a call to `log_json` with extra kwargs `{"retry_count": 3}`, when the log is written, then the JSON object must contain a key `"retry_count": 3`
- AC3: Given the application startup, when `setup_logging` is called, then the root logger must be configured to output to stdout

## Implementation Notes

- Standard lib: `logging`, `json`, `re`
- Redaction uses compiled regex; `log_json` should handle non-serializable objects gracefully (e.g., `str()`)
- Provides mechanism for cross-cutting performance observability (Feature 007)

## Related

- [Original feature doc](../../08_Epics/000_v2_foundation/016_structured_logging_redaction/016_feature.md) — full historical detail
