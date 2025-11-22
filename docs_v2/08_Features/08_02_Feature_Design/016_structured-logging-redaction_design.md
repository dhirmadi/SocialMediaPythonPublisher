<!-- docs_v2/08_Features/08_02_Feature_Design/016_structured-logging-redaction_design.md -->

# Design: Structured Logging & Redaction

## 1. Summary
This feature provides a consistent `publisher_v2.utils.logging` module that wraps the Python standard library logging facilities. It enforces JSON formatting for the log *payload* to ensure machine readability while applying regex-based redaction to sanitize sensitive data.

## 2. Context & Assumptions
- **Current State:** Logging is the primary observability tool.
- **Constraints:** 
  - Minimal dependencies (avoid adding large libraries just for logging).
  - Must be thread-safe and async-safe.
- **Assumptions:**
  - Logs are captured from `stdout`/`stderr` by the platform (Heroku, Docker).

## 3. Requirements
### Functional
- **Sanitization:** Strip patterns matching API keys.
- **Format:** Hybrid Text + JSON.
- **Fields:** `timestamp` (ISO8601), `message`, `**kwargs`.

### Non-Functional
- **Performance:** Regex redaction must be compiled and efficient.
- **Reliability:** Logging itself should not crash the application (handle serialization errors).

## 4. Architecture & Design

### Component: `publisher_v2.utils.logging`

#### `setup_logging(level: int)`
- Configures the root logger.
- Adds a `StreamHandler` (stdout).
- **Formatter:** Sets a standard text formatter (`%(asctime)s - %(name)s - %(levelname)s - %(message)s`).
- **Rationale:** This ensures that standard library logs (from `urllib3` or `dropbox`) are readable in the same stream, while application logs (via `log_json`) output JSON as the `%(message)s` part.

#### `sanitize(message: str) -> str`
- Uses a list of compiled regex patterns `SENSITIVE_PATTERNS`.
- `sk-[A-Za-z0-9]{20,}` -> `[OPENAI_KEY_REDACTED]`
- `[0-9]{6,}:[A-Za-z0-9_-]{20,}` -> `[TELEGRAM_TOKEN_REDACTED]`
- `r8_[A-Za-z0-9]+` -> `[REPLICATE_TOKEN_REDACTED]`

#### `log_json(logger, level, message, **kwargs)`
The primary API for application logging.
1.  `sanitized_msg = sanitize(message)`
2.  `entry = { "timestamp": ..., "message": sanitized_msg, **kwargs }`
3.  `json_str = json.dumps(entry, default=str)` (Handles non-serializable types by converting to string).
4.  `logger.log(level, json_str)`
    - Resulting Output: `TIMESTAMP - LOGGER - LEVEL - {"timestamp": "...", "message": "...", ...}`

## 5. Integration
- **CLI:** Calls `setup_logging` in `app.py` -> `main_async`.
- **Web:** Calls `setup_logging` in `web/app.py` -> `@app.on_event("startup")`.

## 6. Security Considerations
- **Scope:** Redaction applies to the `message` field.
- **Context Fields:** `**kwargs` values are **not** recursively sanitized in the current implementation to save performance. Developers must ensure they do not pass secrets as kwargs (e.g., `log_json(..., token=secret)` is unsafe).
- **Mitigation:** Code review enforcement: "Do not log raw secrets in kwargs".

## 7. Testing Strategy
- **Unit Tests:**
  - Test `sanitize` against known fake keys.
  - Test `log_json` output format (verify it creates a JSON string).
  - Test `setup_logging` configuration.
- **Integration Tests:**
  - Verify logs appear in the expected format during E2E runs.

## 8. Future Improvements
- **JSON Formatter:** Implement a proper `logging.Formatter` subclass that outputs *pure* JSON for all logs (including third-party libraries), removing the text header.
- **Recursive Redaction:** Walk the `kwargs` dictionary to redact secrets in context values.
