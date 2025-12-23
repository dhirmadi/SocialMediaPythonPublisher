# Story: Deprecation Warnings and Documentation

**Feature ID:** 021  
**Story ID:** 021-06  
**Name:** deprecation-docs  
**Status:** Proposed  
**Date:** 2025-12-22  
**Parent Feature:** 021_config_env_consolidation

## Summary

Add deprecation logging when INI fallback is used and update operator documentation with the new `.env` structure. This completes the feature by ensuring operators are guided toward the new configuration approach.

## Scope

- Emit deprecation warning when INI file is used for any configuration
- Log which specific sections triggered fallback (for targeted migration)
- Log config source at startup ("Config loaded from: env_vars" or "Config loaded from: ini_fallback")
- Update `code_v1/dotenv.example` and create `dotenv.v2.example` with new structure
- Create migration guide section in documentation

## Out of Scope

- Removing INI file support (maintained for backward compatibility)
- Automated migration scripts

## Acceptance Criteria

### Deprecation Warnings

- Given all new JSON env vars are set, when config loads, then no deprecation warning is emitted.
- Given `PUBLISHERS` is not set and INI `[Content] telegram = true` is used, when config loads, then a deprecation warning is logged: "DEPRECATION: Using INI file for publishers config. Migrate to PUBLISHERS env var."
- Given any INI fallback occurs, when config loads, then the startup log shows: "Config source: ini_fallback (migrate to env vars)"
- Given all env vars are used, when config loads, then the startup log shows: "Config source: env_vars"

### Documentation

- Given an operator reads `dotenv.v2.example`, then they can see all new JSON env vars with example values.
- Given an operator reads the migration guide, then they understand how to convert INI to new env vars.

## Technical Notes

Deprecation log format:
```python
log_json(
    logger,
    logging.WARNING,
    "config_deprecation",
    source="ini_fallback",
    sections=["Content", "Email", "openAI"],  # List of INI sections used
    message="INI-based config is deprecated. Migrate to JSON env vars.",
)
```

Startup log:
```python
log_json(
    logger,
    logging.INFO,
    "config_loaded",
    source="env_vars",  # or "ini_fallback"
    publishers_count=2,
    storage_source="STORAGE_PATHS",  # or "INI"
)
```

Documentation files to update:
- `code_v1/dotenv.example` → add note pointing to new structure
- Create `dotenv.v2.example` with full new structure
- Add migration section to `docs_v2/05_Configuration/CONFIGURATION.md`

## Dependencies

- Stories 01-05 (all parsing logic must be complete to know when INI fallback is used)

