# Story Summary: Storage Paths Environment Variable

**Feature ID:** 021  
**Story ID:** 021-04  
**Status:** Shipped  
**Date Completed:** 2025-12-23

## Summary

Implemented the `_load_storage_paths_from_env()` function to parse the `STORAGE_PATHS` JSON environment variable for Dropbox folder configuration. Includes helper functions for path resolution and security validation.

## Files Changed

### Source Files
- `publisher_v2/src/publisher_v2/config/loader.py` — Added:
  - `_resolve_path(base, path)` — Resolves relative paths against base, preserves absolute paths
  - `_validate_path_no_traversal(path, field)` — Raises ConfigurationError if path contains '..' component
  - `_load_storage_paths_from_env()` — Main function that:
    - Parses STORAGE_PATHS JSON object
    - Validates required `root` field (must be absolute path)
    - Resolves optional archive, keep, remove paths relative to root
    - Provides defaults: archive="archive", keep="keep", remove="reject"
    - Validates no path traversal (..) in any resolved path

### Test Files
- `publisher_v2/tests/config/test_loader_env_helpers.py` — Added:
  - `TestResolvePath` class (3 tests): relative resolution, absolute preservation, trailing slash handling
  - `TestValidatePathNoTraversal` class (3 tests): normal paths, double-dot rejection, dots in filenames
  - `TestLoadStoragePathsFromEnv` class (8 tests):
    - Returns None when unset
    - Parses minimal config (root only)
    - Parses full config (all fields)
    - Preserves absolute subpaths
    - Raises when root missing
    - Raises when root not absolute
    - Raises when root has path traversal
    - Raises when archive has path traversal

## Test Results

- Tests: 14 passed, 0 failed
- Coverage: Full coverage of new functions

## Acceptance Criteria Status

- [x] AC1: Given valid STORAGE_PATHS JSON with root, archive, keep, remove, parser returns resolved paths
- [x] AC2: Given STORAGE_PATHS with only root, parser uses defaults for archive/keep/remove relative to root
- [x] AC3: Given STORAGE_PATHS with relative subpaths, parser resolves them against root
- [x] AC4: Given STORAGE_PATHS with absolute subpaths, parser preserves them as-is
- [x] AC5: Given STORAGE_PATHS missing root, parser raises ConfigurationError
- [x] AC6: Given STORAGE_PATHS with root not starting with '/', parser raises ConfigurationError
- [x] AC7: Given STORAGE_PATHS with '..' in any path component, parser raises ConfigurationError

## Follow-up Items

- None — ready for integration in Story 06

## Artifacts

- Story Definition: 021_04_storage-paths-env-var.md
- Story Design: 021_04_design.md
- Story Plan: 021_04_plan.yaml

