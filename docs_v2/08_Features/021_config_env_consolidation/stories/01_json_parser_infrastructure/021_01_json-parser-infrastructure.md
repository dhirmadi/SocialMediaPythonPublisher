# Story: JSON Config Parser Infrastructure

**Feature ID:** 021  
**Story ID:** 021-01  
**Name:** json-parser-infrastructure  
**Status:** Proposed  
**Date:** 2025-12-22  
**Parent Feature:** 021_config_env_consolidation

## Summary

Add JSON parsing helpers and error handling infrastructure to the config loader module. This provides the foundation for all subsequent stories that parse JSON environment variables.

## Scope

- Add `_parse_json_env(var_name: str) -> Optional[dict | list]` helper function
- Implement clear error messages for JSON parse failures with position info
- Add `_safe_log_config()` helper for redacting secrets in log output
- Add type stubs for parsed JSON structures (TypedDict or similar)

## Out of Scope

- Actual parsing of specific environment variables (PUBLISHERS, EMAIL_SERVER, etc.)
- Changes to existing configuration loading logic
- Migration documentation

## Acceptance Criteria

- Given a valid JSON string in an environment variable, when `_parse_json_env` is called, then it returns the parsed dict/list.
- Given an invalid JSON string, when `_parse_json_env` is called, then it raises `ConfigurationError` with the parse error position.
- Given an empty or unset environment variable, when `_parse_json_env` is called, then it returns `None`.
- Given a config dict with sensitive keys (password, token), when `_safe_log_config` is called, then those values are redacted.

## Technical Notes

From the feature design:

```python
def _parse_json_env(var_name: str) -> Optional[dict | list]:
    value = os.environ.get(var_name)
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Invalid JSON in {var_name}: {exc.msg} at position {exc.pos}"
        ) from exc
```

Redaction keys should include: `password`, `secret`, `token`, `refresh_token`, `bot_token`, `api_key`.

## Dependencies

- None (foundational story)

