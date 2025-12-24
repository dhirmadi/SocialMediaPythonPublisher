# Implementation Story: 03_proactive_folder_creation

This story covers the proactive folder creation defined in 010_03_plan.yaml.

## Context
This story implements a change request to ensure Keep/Remove folders exist when an admin logs in, preventing errors during later curation actions.

## Plan Execution

### 1. Storage Layer
*   **Helper**: Added `ensure_folder_exists` to `DropboxStorage` in `publisher_v2/services/storage.py`.
    *   Wraps `files_create_folder_v2`.
    *   Handles `ApiError` to ignore "path already exists" errors.
    *   Raises `StorageError` for other failures.

### 2. Web Service
*   **Verification Logic**: Added `verify_curation_folders` to `WebImageService` in `publisher_v2/web/service.py`.
    *   Checks `features.keep_enabled`. If true and `folder_keep` is set, ensures the folder exists.
    *   Checks `features.remove_enabled`. If true and `folder_remove` is set, ensures the folder exists.
    *   Constructs full paths relative to `image_folder`.
    *   Logs the outcome.

### 3. Web Endpoint
*   **Integration**: Updated `api_admin_login` in `publisher_v2/web/app.py`.
    *   Now accepts `WebImageService` dependency.
    *   Calls `service.verify_curation_folders()` after successful auth.
    *   Catches and logs exceptions from verification to ensure login doesn't fail due to transient storage issues (soft failure).

## Verification
*   **Tests**:
    *   `publisher_v2/tests/web/test_web_admin_login_folder_check.py`:
        *   Mock `DropboxStorage` to verify `ensure_folder_exists` is called with correct paths.
        *   Verify feature flags are respected (no calls if disabled).
        *   Verify folder paths handle trailing slashes correctly.
