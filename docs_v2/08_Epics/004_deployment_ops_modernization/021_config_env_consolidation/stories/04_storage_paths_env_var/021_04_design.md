# Storage Paths Environment Variable — Story Design

**Feature ID:** 021  
**Story ID:** 021-04  
**Parent Feature:** config_env_consolidation  
**Design Version:** 1.0  
**Date:** 2025-12-23  
**Status:** Design Review  
**Story Definition:** 021_04_storage-paths-env-var.md  
**Parent Feature Design:** ../../021_design.md

## 1. Summary

### Problem & Context
Storage paths (image_folder, archive, keep, remove) are currently in INI `[Dropbox]` section. The Orchestrator API (Epic 001) will provide absolute paths. This story adds `STORAGE_PATHS` JSON parsing that supports both absolute and relative paths for backward compatibility.

### Goals
- Parse `STORAGE_PATHS` JSON for Dropbox folder configuration
- Support absolute paths (used as-is, aligned with Orchestrator API)
- Support relative paths (joined with root, backward compatible with INI)
- Validate root is absolute and paths don't contain `..`
- Implement precedence: `STORAGE_PATHS` > individual env vars > INI

### Non-Goals
- Dropbox credentials (remain in individual env vars)
- File operations or storage service changes
- Changing DropboxConfig Pydantic model

## 2. Context & Assumptions

### Current Behavior
`loader.py` lines 62-110:
```python
image_folder = cp.get("Dropbox", "image_folder")
archive_folder = cp.get("Dropbox", "archive", fallback="archive")
folder_keep = cp.get("Dropbox", "folder_keep", fallback="keep")
folder_remove = cp.get("Dropbox", "folder_remove", fallback=None)
# ... validation and DropboxConfig creation
```

### Constraints
- Root path must be absolute (starts with `/`)
- Paths must not contain `..` (security)
- Dropbox uses `/` separator even on Windows
- Must fall back to INI if `STORAGE_PATHS` not set

### Dependencies
- Story 01: `_parse_json_env()` helper

## 3. Requirements

### 3.1 Functional Requirements

**SR1:** Parse `STORAGE_PATHS` env var as JSON object with fields:
- `root` (required, must be absolute)
- `archive` (optional, default: "archive")
- `keep` (optional, default: "keep")
- `remove` (optional, default: "reject")

**SR2:** Path resolution:
- If path starts with `/`: use as-is (absolute)
- Otherwise: join with root (relative)

**SR3:** Validation:
- Root must start with `/`
- No path may contain `..` component

**SR4:** Precedence: `STORAGE_PATHS` > `folder_keep`/`folder_remove` env vars > INI

### 3.2 Non-Functional Requirements

**NFR1:** Path resolution is deterministic and testable

**NFR2:** Clear error messages for validation failures

## 4. Architecture & Design (Delta)

### 4.1 Current vs. Proposed

**Current:**
```python
image_folder = cp.get("Dropbox", "image_folder")
archive_folder = cp.get("Dropbox", "archive", fallback="archive")
```

**Proposed:**
```python
storage_paths = _load_storage_paths_from_env()
if storage_paths:
    image_folder = storage_paths["root"]
    archive_folder = storage_paths["archive"]
    folder_keep = storage_paths["keep"]
    folder_remove = storage_paths["remove"]
else:
    # Fallback to existing INI logic
```

### 4.2 Components & Responsibilities

**`config/loader.py`** (modified):
- Add `_resolve_path(base: str, path: str) -> str` helper
- Add `_validate_path_no_traversal(path: str, field: str) -> None` helper
- Add `_load_storage_paths_from_env() -> Optional[dict]`

### 4.3 Data & Contracts

**STORAGE_PATHS JSON Schema:**
```json
{
  "root": "/Photos/2025",           // required, absolute
  "archive": "/Photos/2025/archive", // optional, absolute or relative
  "keep": "approve",                 // optional, relative to root
  "remove": "reject"                 // optional, relative to root
}
```

**Output dict:**
```python
{
    "root": str,      # The root path (always absolute)
    "archive": str,   # Resolved absolute path
    "keep": str,      # Resolved absolute path
    "remove": str,    # Resolved absolute path
}
```

### 4.4 Error Handling & Edge Cases

**Root not absolute:**
```python
if not root.startswith("/"):
    raise ConfigurationError(
        "STORAGE_PATHS.root must be an absolute path (start with '/')"
    )
```

**Path traversal attempt:**
```python
def _validate_path_no_traversal(path: str, field: str) -> None:
    if ".." in path.split("/"):
        raise ConfigurationError(
            f"STORAGE_PATHS.{field} contains '..' which is not allowed"
        )
```

**Relative path resolution:**
```python
def _resolve_path(base: str, path: str) -> str:
    if path.startswith("/"):
        return path  # Already absolute
    return f"{base.rstrip('/')}/{path}"
```

### 4.5 Security, Privacy, Compliance

- `..` rejection prevents path traversal attacks
- Root must be absolute prevents relative path confusion

## 5. Detailed Flow

### `_load_storage_paths_from_env` Flow

```
1. parsed = _parse_json_env("STORAGE_PATHS")
2. If parsed is None:
   └─ Return None
3. Extract root (required):
   └─ If missing: raise ConfigurationError
4. Validate root is absolute:
   └─ If not starts with '/': raise ConfigurationError
5. Validate root has no '..':
   └─ If has: raise ConfigurationError
6. Extract optional paths with defaults:
   ├─ archive = parsed.get("archive", "archive")
   ├─ keep = parsed.get("keep", "keep")
   └─ remove = parsed.get("remove", "reject")
7. Resolve each path:
   ├─ archive = _resolve_path(root, archive)
   ├─ keep = _resolve_path(root, keep)
   └─ remove = _resolve_path(root, remove)
8. Validate no path has '..':
   └─ For each: if has '..': raise ConfigurationError
9. Return {"root": root, "archive": archive, "keep": keep, "remove": remove}
```

### Integration with DropboxConfig

```python
storage_paths = _load_storage_paths_from_env()
if storage_paths:
    dropbox = DropboxConfig(
        app_key=os.environ["DROPBOX_APP_KEY"],
        app_secret=os.environ["DROPBOX_APP_SECRET"],
        refresh_token=os.environ["DROPBOX_REFRESH_TOKEN"],
        image_folder=storage_paths["root"],
        archive_folder=storage_paths["archive"],
        folder_keep=storage_paths["keep"],
        folder_remove=storage_paths["remove"],
    )
```

## 6. Testing Strategy

### Unit Tests

| Test Case | Input | Expected |
|-----------|-------|----------|
| All absolute | `{"root": "/a", "archive": "/a/b", "keep": "/a/c", "remove": "/a/d"}` | All used as-is |
| Mixed relative | `{"root": "/a", "archive": "b", "keep": "c"}` | archive="/a/b", keep="/a/c", remove="/a/reject" |
| Root only | `{"root": "/a"}` | Defaults: archive="/a/archive", keep="/a/keep", remove="/a/reject" |
| Root not absolute | `{"root": "relative"}` | ConfigurationError |
| Path with `..` | `{"root": "/a", "archive": "../etc"}` | ConfigurationError |
| Missing root | `{"archive": "/a/b"}` | ConfigurationError |
| Not set | None | Returns None |

### Test File
`publisher_v2/tests/config/test_loader_storage_paths.py`

## 7. Risks & Alternatives

### Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Windows path separators | Low | Medium | Dropbox uses `/` always; document this |
| Trailing slashes inconsistency | Low | Low | Strip trailing `/` from root before joining |

### Alternatives Considered

1. **Use pathlib**: Adds complexity; string operations sufficient for Dropbox paths
2. **Allow relative root**: Rejected; absolute root prevents ambiguity

## 8. Work Plan

### Tasks

1. Add `_resolve_path(base, path)` helper
2. Add `_validate_path_no_traversal(path, field)` helper
3. Add `_load_storage_paths_from_env()` function
4. Update `load_application_config()` to use STORAGE_PATHS
5. Write unit tests for all scenarios

### Definition of Done

- [ ] STORAGE_PATHS parsed with path resolution
- [ ] Root validated as absolute
- [ ] `..` rejected in all paths
- [ ] Relative paths joined with root correctly
- [ ] Defaults applied for optional fields
- [ ] Unit tests cover all edge cases

