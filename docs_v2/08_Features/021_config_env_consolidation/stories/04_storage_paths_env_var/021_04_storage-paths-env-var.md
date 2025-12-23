# Story: Storage Paths Environment Variable

**Feature ID:** 021  
**Story ID:** 021-04  
**Name:** storage-paths-env-var  
**Status:** Proposed  
**Date:** 2025-12-22  
**Parent Feature:** 021_config_env_consolidation

## Summary

Implement `STORAGE_PATHS` JSON parsing with absolute/relative path handling. This aligns with the Orchestrator API contract where paths are provided as absolute paths, while maintaining backward compatibility with the current relative-path INI configuration.

## Scope

- Parse `STORAGE_PATHS` environment variable as JSON object
- Support absolute paths (start with `/`) used as-is
- Support relative paths (for archive/keep/remove) joined with root
- Apply to `DropboxConfig`: `image_folder`, `archive_folder`, `folder_keep`, `folder_remove`
- Implement precedence: `STORAGE_PATHS` > individual env vars (`folder_keep`, `folder_remove`) > INI

## Out of Scope

- Dropbox credentials (remain in individual env vars: `DROPBOX_APP_KEY`, etc.)
- File operations or storage service changes

## Acceptance Criteria

- Given `STORAGE_PATHS='{"root": "/Photos/2025", "archive": "/Photos/2025/archive", "keep": "/Photos/2025/approve", "remove": "/Photos/2025/reject"}'` (all absolute), when config loads, then all paths are used as-is.
- Given `STORAGE_PATHS='{"root": "/Photos/2025", "archive": "archive", "keep": "approve", "remove": "reject"}'` (relative), when config loads, then archive becomes `/Photos/2025/archive`, keep becomes `/Photos/2025/approve`, etc.
- Given `STORAGE_PATHS` contains only `root`, when config loads, then defaults are used for archive/keep/remove (archive=`archive`, keep=`keep`, remove=`reject`).
- Given `STORAGE_PATHS.root` does not start with `/`, when config loads, then `ConfigurationError` is raised (root must be absolute).
- Given `STORAGE_PATHS` contains an absolute path with a `..` component (e.g., `/Photos/../etc`), when config loads, then `ConfigurationError` is raised.
- Given `STORAGE_PATHS` is not set, when config loads, then fallback to INI `[Dropbox]` section occurs.
- Given `STORAGE_PATHS` and `folder_keep` env var both exist, when config loads, then `STORAGE_PATHS.keep` takes precedence.

## Technical Notes

Path handling logic:
```python
def _resolve_path(base: str, path: str) -> str:
    if path.startswith("/"):
        return path  # Absolute path
    return f"{base.rstrip('/')}/{path}"  # Relative to base
```

Validation:
- `root` is required and must be absolute
- `archive`, `keep`, `remove` are optional with defaults
- Path separators: Dropbox uses `/` even on Windows

Alignment with Orchestrator API (Epic 001):
```json
"storage": {
  "paths": {
    "root": "/some/root/path",
    "archive": "/some/root/path/archive",
    "keep": "/some/root/path/keep",
    "remove": "/some/root/path/remove"
  }
}
```

## Dependencies

- Story 01: JSON Parser Infrastructure

