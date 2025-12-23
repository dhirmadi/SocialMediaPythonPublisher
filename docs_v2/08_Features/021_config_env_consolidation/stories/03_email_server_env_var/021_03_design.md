# Email Server Environment Variable — Story Design

**Feature ID:** 021  
**Story ID:** 021-03  
**Parent Feature:** config_env_consolidation  
**Design Version:** 1.0  
**Date:** 2025-12-23  
**Status:** Design Review  
**Story Definition:** 021_03_email-server-env-var.md  
**Parent Feature Design:** ../../021_design.md

## 1. Summary

### Problem & Context
Email infrastructure settings (SMTP server, port, sender) are currently in the INI `[Email]` section, while the password is in `.env`. This story consolidates non-secret email settings into `EMAIL_SERVER` JSON, while keeping `EMAIL_PASSWORD` as a flat secret env var.

### Goals
- Parse `EMAIL_SERVER` JSON for SMTP settings (smtp_server, smtp_port, sender)
- Password continues to come from `EMAIL_PASSWORD` flat env var
- Implement precedence: `EMAIL_SERVER` > individual env vars > INI
- Validate required fields and types

### Non-Goals
- Publisher array parsing (Story 02)
- Confirmation email settings (Story 05)
- Embedding password in JSON (explicitly rejected per feature design)

## 2. Context & Assumptions

### Current Behavior
`loader.py` lines 170-182:
```python
email = EmailConfig(
    sender=cp.get("Email", "sender"),
    recipient=cp.get("Email", "recipient"),
    password=os.environ["EMAIL_PASSWORD"],
    smtp_server=cp.get("Email", "smtp_server", fallback=os.environ.get("SMTP_SERVER", "smtp.gmail.com")),
    smtp_port=cp.getint("Email", "smtp_port", fallback=int(os.environ.get("SMTP_PORT", "587"))),
    ...
)
```

### Constraints
- `EMAIL_PASSWORD` must remain a flat env var (not in JSON)
- Must fall back to INI/env vars if `EMAIL_SERVER` not set
- smtp_port must be an integer

### Dependencies
- Story 01: `_parse_json_env()` helper
- Story 02 consumes EMAIL_SERVER output for FetLife EmailConfig

## 3. Requirements

### 3.1 Functional Requirements

**SR1:** Parse `EMAIL_SERVER` env var as JSON object with fields:
- `smtp_server` (optional, default: "smtp.gmail.com")
- `smtp_port` (optional, default: 587)
- `sender` (required)

**SR2:** Password comes from `EMAIL_PASSWORD` flat env var

**SR3:** Precedence order:
1. `EMAIL_SERVER` JSON fields
2. Individual env vars (`SMTP_SERVER`, `SMTP_PORT`)
3. INI `[Email]` section

**SR4:** If `EMAIL_SERVER` is set but `EMAIL_PASSWORD` is missing when FetLife is enabled, raise `ConfigurationError`

**SR5:** Validate `smtp_port` is an integer

### 3.2 Non-Functional Requirements

**NFR1:** Password never logged

**NFR2:** Clear error messages for type validation failures

## 4. Architecture & Design (Delta)

### 4.1 Current vs. Proposed

**Current:**
```python
smtp_server=cp.get("Email", "smtp_server", fallback=os.environ.get("SMTP_SERVER", "smtp.gmail.com"))
```

**Proposed:**
```python
email_server = _load_email_server_from_env()
if email_server:
    smtp_server = email_server["smtp_server"]
    smtp_port = email_server["smtp_port"]
    sender = email_server["sender"]
else:
    # Fallback to existing logic
```

### 4.2 Components & Responsibilities

**`config/loader.py`** (modified):
- Add `_load_email_server_from_env() -> Optional[dict]`
- Returns dict with smtp_server, smtp_port, sender (with defaults applied)
- Returns `None` if EMAIL_SERVER not set

### 4.3 Data & Contracts

**EMAIL_SERVER JSON Schema:**
```json
{
  "smtp_server": "smtp.gmail.com",  // optional, default: smtp.gmail.com
  "smtp_port": 587,                  // optional, default: 587
  "sender": "user@gmail.com"         // required
}
```

**Output dict:**
```python
{
    "smtp_server": str,
    "smtp_port": int,
    "sender": str,
}
```

### 4.4 Error Handling & Edge Cases

**Missing required sender:**
```python
if "sender" not in parsed:
    raise ConfigurationError(
        "EMAIL_SERVER missing required field 'sender'"
    )
```

**Invalid smtp_port type:**
```python
port = parsed.get("smtp_port", 587)
if not isinstance(port, int):
    raise ConfigurationError(
        f"EMAIL_SERVER.smtp_port must be an integer, got {type(port).__name__}"
    )
```

**EMAIL_PASSWORD missing when FetLife enabled:**
- This validation happens in Story 02 when creating EmailConfig
- Story 03 just provides the server settings

### 4.5 Security, Privacy, Compliance

- Password explicitly NOT in EMAIL_SERVER JSON
- Use `_safe_log_config` when logging email server settings

## 5. Detailed Flow

### `_load_email_server_from_env` Flow

```
1. parsed = _parse_json_env("EMAIL_SERVER")
2. If parsed is None:
   └─ Return None (caller will use fallback)
3. Validate sender is present:
   └─ If not: raise ConfigurationError
4. Apply defaults:
   ├─ smtp_server = parsed.get("smtp_server", "smtp.gmail.com")
   └─ smtp_port = parsed.get("smtp_port", 587)
5. Validate smtp_port is int:
   └─ If not: raise ConfigurationError
6. Return {"smtp_server": ..., "smtp_port": ..., "sender": ...}
```

### Integration with Story 02

Story 02's `_load_publishers_from_env` will call:
```python
email_server = _load_email_server_from_env()
if email_server:
    # Use EMAIL_SERVER values
    smtp_server = email_server["smtp_server"]
    sender = email_server["sender"]
else:
    # Use INI/env fallback
    smtp_server = cp.get("Email", "smtp_server", fallback=...)
```

## 6. Testing Strategy

### Unit Tests

| Test Case | Input | Expected |
|-----------|-------|----------|
| Full EMAIL_SERVER | `{"smtp_server": "x", "smtp_port": 465, "sender": "a@b"}` | Dict with all values |
| Minimal (sender only) | `{"sender": "a@b"}` | Dict with defaults for server/port |
| Missing sender | `{"smtp_server": "x"}` | ConfigurationError |
| Invalid port type | `{"sender": "a@b", "smtp_port": "587"}` | ConfigurationError |
| Not set | None | Returns None |
| Empty string | `''` | Returns None |
| Invalid JSON | `'{"sender":'` | ConfigurationError from _parse_json_env |

### Test File
`publisher_v2/tests/config/test_loader_email_server.py`

## 7. Risks & Alternatives

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Port as string in JSON | Medium | Low | Validate type and provide clear error |

### Alternatives Considered

1. **Include password in JSON**: Rejected per feature design (secrets must be flat env vars)
2. **Make sender optional**: Rejected; sender is required for SMTP

## 8. Work Plan

### Tasks

1. Add `_load_email_server_from_env()` function
2. Add validation for required sender field
3. Add validation for smtp_port integer type
4. Write unit tests
5. Update Story 02 to consume EMAIL_SERVER

### Definition of Done

- [ ] EMAIL_SERVER parsed with defaults applied
- [ ] sender validated as required
- [ ] smtp_port validated as integer
- [ ] Returns None when not set (enables fallback)
- [ ] Unit tests cover all edge cases
- [ ] Password NOT in EMAIL_SERVER (verified by code review)

