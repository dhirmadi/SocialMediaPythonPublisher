# JSON Config Parser Infrastructure — Story Design

**Feature ID:** 021  
**Story ID:** 021-01  
**Parent Feature:** config_env_consolidation  
**Design Version:** 1.0  
**Date:** 2025-12-23  
**Status:** Design Review  
**Story Definition:** 021_01_json-parser-infrastructure.md  
**Parent Feature Design:** ../../021_design.md

## 1. Summary

### Problem & Context
The config loader needs to parse JSON-encoded environment variables for the new consolidated configuration approach. Currently, the loader only handles INI files and simple env vars. This story adds the foundational JSON parsing infrastructure that all subsequent stories depend on.

### Goals
- Add reusable JSON parsing helper with clear error messages
- Add secret redaction helper for safe logging
- Provide TypedDict definitions for parsed JSON structures
- Fail fast on invalid JSON with actionable error messages

### Non-Goals
- Parsing specific env vars (PUBLISHERS, EMAIL_SERVER, etc.) — handled in Stories 02-05
- Changing existing INI loading logic
- Adding precedence logic (handled in subsequent stories)

## 2. Context & Assumptions

### Current Behavior
`publisher_v2/config/loader.py`:
- Uses `configparser` for INI files
- Uses `os.environ.get()` for individual env vars
- Constructs Pydantic models from parsed values
- No JSON parsing capability

### Constraints
- Must remain synchronous (NFR3 from feature design)
- Must not log secrets (NFR2 from feature design)
- Must integrate cleanly with existing loader structure

### Dependencies
- `json` (stdlib) — for JSON parsing
- `publisher_v2.core.exceptions.ConfigurationError` — for error reporting

## 3. Requirements

### 3.1 Functional Requirements

**SR1:** `_parse_json_env(var_name: str) -> Optional[dict | list]`
- Returns parsed JSON if env var is set and valid
- Returns `None` if env var is unset or empty
- Raises `ConfigurationError` with position info on parse failure

**SR2:** `_safe_log_config(cfg: dict, redact_keys: set[str]) -> dict`
- Returns a copy of config dict with sensitive values redacted
- Redaction keys: `password`, `secret`, `token`, `refresh_token`, `bot_token`, `api_key`

**SR3:** TypedDict definitions for JSON structures
- `PublisherEntry`, `EmailServerConfig`, `StoragePathsConfig`, etc.
- Enable type checking in downstream parsing functions

### 3.2 Non-Functional Requirements

**NFR1:** JSON parsing must not regress startup time (O(1) for reasonable sizes)

**NFR2:** Secret values must never appear in logs when using `_safe_log_config`

## 4. Architecture & Design (Delta)

### 4.1 Current vs. Proposed

**Current:** No JSON parsing in loader

**Proposed:** Add helper functions at module level in `loader.py`:
```python
# publisher_v2/config/loader.py

def _parse_json_env(var_name: str) -> Optional[dict | list]:
    """Parse JSON from environment variable, returning None if unset."""
    ...

def _safe_log_config(cfg: dict, redact_keys: set[str] | None = None) -> dict:
    """Return config dict with sensitive values redacted for logging."""
    ...
```

### 4.2 Components & Responsibilities

**`config/loader.py`** (modified):
- Add `_parse_json_env()` helper
- Add `_safe_log_config()` helper  
- Add `REDACT_KEYS` constant for default sensitive key names

**`config/types.py`** (new file, optional):
- TypedDict definitions for JSON schemas
- Can be inline in loader.py if preferred for simplicity

### 4.3 Data & Contracts

```python
from typing import TypedDict, Optional, Literal

class PublisherEntryBase(TypedDict):
    type: str

class TelegramPublisherEntry(TypedDict):
    type: Literal["telegram"]
    channel_id: str

class FetLifePublisherEntry(TypedDict):
    type: Literal["fetlife"]
    recipient: str
    caption_target: str  # "subject" | "body" | "both"
    subject_mode: str    # "normal" | "private" | "avatar"

class InstagramPublisherEntry(TypedDict):
    type: Literal["instagram"]
    username: str

class EmailServerConfig(TypedDict, total=False):
    smtp_server: str
    smtp_port: int
    sender: str  # required

class StoragePathsConfig(TypedDict, total=False):
    root: str  # required
    archive: str
    keep: str
    remove: str

# Default keys to redact in logs
REDACT_KEYS: set[str] = {
    "password", "secret", "token", 
    "refresh_token", "bot_token", "api_key"
}
```

### 4.4 Error Handling & Edge Cases

**Invalid JSON:**
```python
try:
    return json.loads(value)
except json.JSONDecodeError as exc:
    raise ConfigurationError(
        f"Invalid JSON in {var_name}: {exc.msg} at position {exc.pos}"
    ) from exc
```

**Empty/whitespace value:** Treat as unset, return `None`

**Nested secrets:** `_safe_log_config` only redacts top-level keys; nested dicts are not recursively redacted (acceptable for current use case)

### 4.5 Security, Privacy, Compliance

- `_safe_log_config` prevents accidental secret exposure in logs
- No secrets should be embedded in JSON env vars (policy enforced by design, not code)

## 5. Detailed Flow

### `_parse_json_env` Flow

```
1. Get value from os.environ.get(var_name)
2. If value is None or empty string:
   └─ Return None
3. Try json.loads(value):
   ├─ Success: Return parsed dict/list
   └─ JSONDecodeError: Raise ConfigurationError with position info
```

### `_safe_log_config` Flow

```
1. If redact_keys is None, use REDACT_KEYS default
2. For each key in cfg:
   ├─ If key.lower() matches any redact_key: value = "***REDACTED***"
   └─ Else: keep original value
3. Return new dict with redacted values
```

## 6. Testing Strategy

### Unit Tests

| Test Case | Input | Expected |
|-----------|-------|----------|
| Parse valid JSON object | `'{"key": "value"}'` | `{"key": "value"}` |
| Parse valid JSON array | `'[1, 2, 3]'` | `[1, 2, 3]` |
| Parse invalid JSON | `'{"key": }'` | `ConfigurationError` with position |
| Unset env var | `None` | `None` |
| Empty string | `''` | `None` |
| Whitespace only | `'   '` | `None` |
| Redact password key | `{"password": "secret"}` | `{"password": "***REDACTED***"}` |
| Redact bot_token key | `{"bot_token": "123"}` | `{"bot_token": "***REDACTED***"}` |
| Keep non-sensitive key | `{"name": "test"}` | `{"name": "test"}` |
| Case insensitive redact | `{"PASSWORD": "x"}` | `{"PASSWORD": "***REDACTED***"}` |

### Test File
`publisher_v2/tests/config/test_loader_json_helpers.py`

## 7. Risks & Alternatives

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| JSON parsing slower than expected | Low | Low | Parsing is fast for small configs |
| Nested secrets not redacted | Medium | Medium | Document limitation; current schemas don't nest secrets |

### Alternatives Considered

1. **Use Pydantic `TypeAdapter.validate_json`**: More validation, but adds complexity for foundational story. Can adopt in Story 02+ if needed.
2. **Separate `env_parsers.py` module**: Adds file overhead; inline in loader.py is simpler for now.

## 8. Work Plan

### Tasks

1. Add `REDACT_KEYS` constant to `loader.py`
2. Implement `_parse_json_env()` function
3. Implement `_safe_log_config()` function
4. Add TypedDict definitions (inline or separate file)
5. Write unit tests for all edge cases
6. Update module docstring

### Definition of Done

- [ ] `_parse_json_env` handles valid JSON, invalid JSON, and missing env vars
- [ ] `_safe_log_config` redacts all sensitive keys
- [ ] Unit tests cover all edge cases from testing strategy
- [ ] No secrets logged in any code path
- [ ] Code follows existing loader.py patterns

