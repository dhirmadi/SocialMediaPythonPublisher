# Implementation Story: 04_default_folder_values

This story covers the default values fix defined in 010_04_plan.yaml.

## Context
The "target subfolder not configured" error occurs because the configuration schema previously defaulted curation folders to `None`. While flexible, this caused runtime errors for users who enabled the feature flag but didn't explicitly set folder names. This story applies sensible defaults ("keep" and "reject") to ensure "it just works".

## Plan Execution

### 1. Schema Defaults
*   **Update**: Modified `DropboxConfig` in `publisher_v2/config/schema.py`:
    *   `folder_keep`: Default changed from `None` to `"keep"`.
    *   `folder_remove`: Default changed from `None` to `"reject"` (matching legacy convention).
    *   Updated type hints to `str` (was `Optional[str]`), though Pydantic still handles optional input.

### 2. Loader Defaults
*   **Update**: Modified `load_application_config` in `publisher_v2/config/loader.py`:
    *   Changed `cp.get(..., fallback=None)` to use `"keep"` and `None` (for remove, to support alias logic).
    *   If `folder_remove` remains `None` (no explicit key and no legacy `folder_reject`), it now defaults to `"reject"`.

## Verification
*   **Tests**:
    *   `test_config_keep_remove_defaults.py`:
        *   Verify that loading an empty/minimal config results in "keep" and "reject" folders.
        *   Verify that explicit values override defaults.
        *   Verify legacy `folder_reject` still works and takes precedence over the default "reject".

