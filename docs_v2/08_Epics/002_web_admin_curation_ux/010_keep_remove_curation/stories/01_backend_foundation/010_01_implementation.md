# Implementation Story: 01_backend_foundation

This story covers the backend foundation defined in 010_01_plan.yaml.

## Context
This story establishes the core backend capabilities for Keep/Remove curation, ensuring that storage moves are safe, configurable, and integrated into the workflow orchestrator.

## Plan Execution

### 1. Config & Schema
*   **Schema Update**: Updated `DropboxConfig` in `publisher_v2/config/schema.py` to include optional `folder_keep` and `folder_remove` fields.
*   **Loader Logic**: Updated `load_application_config` in `publisher_v2/config/loader.py`:
    *   Loads `folder_keep` and `folder_remove` from INI.
    *   Handles legacy `folder_reject` as an alias for `folder_remove` if not explicitly set.
    *   Applies environment variable overrides (`folder_keep`, `folder_remove`).
    *   Validates folder names are safe (no slashes or `..`).
*   **Feature Flags**: Extended `FeaturesConfig` and loader to parse `FEATURE_KEEP_CURATE` and `FEATURE_REMOVE_CURATE`.

### 2. Storage Layer
*   **Move Helper**: Added `move_image_with_sidecars` to `DropboxStorage` in `publisher_v2/services/storage.py`.
    *   Creates destination subfolder if needed.
    *   Moves the image file and attempts to move the `.txt` sidecar.
*   **Refactor**: Updated `archive_image` to reuse `move_image_with_sidecars`.

### 3. Workflow Orchestrator
*   **Curation Methods**: Added `keep_image` and `remove_image` methods to `WorkflowOrchestrator` in `publisher_v2/core/workflow.py`.
*   **Preview Safety**: Implemented `_curate_image` helper that:
    *   Checks feature enablement.
    *   Uses `preview.print_curation_action` (added to `utils/preview.py`) in `preview_mode` or `dry_run`, avoiding any Dropbox calls.
    *   Calls storage only in live mode.

## Verification
*   **Tests**:
    *   `test_config_keep_remove.py`: Verifies config loading, aliasing, and validation.
    *   `test_dropbox_keep_remove_move.py`: Verifies storage moves and sidecar handling.
    *   `test_workflow_keep_remove.py`: Verifies orchestrator logic, including feature flags and preview safety.

