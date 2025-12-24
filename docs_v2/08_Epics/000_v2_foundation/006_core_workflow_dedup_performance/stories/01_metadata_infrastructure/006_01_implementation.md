# Implementation Story: 01_metadata_infrastructure

This story covers the infrastructure changes defined in 006_01_plan.yaml.

## Context
To enable faster de-duplication, we needed the underlying storage capability to retrieve Dropbox metadata (specifically `content_hash`) and the state management capability to persist these hashes alongside our legacy SHA256 hashes.

## Plan Execution

### 1. Storage Layer
*   **Method**: Added `list_images_with_hashes` to `DropboxStorage` in `publisher_v2/services/storage.py`.
    *   Calls `files_list_folder`.
    *   Parses `FileMetadata` to extract `name` and `content_hash`.
    *   Returns a list of tuples `(filename, hash)`.

### 2. State Management
*   **Extensions**: Updated `publisher_v2/utils/state.py`.
    *   Added `load_posted_content_hashes()`: Reads the new `dropbox_content_hashes` key from `posted.json`.
    *   Added `save_posted_content_hash(hash)`: Appends to the list and saves back to JSON.
    *   Ensured backward compatibility: existing `posted.json` files without this key are read correctly (empty set returned).

## Verification
*   **Tests**:
    *   `test_utils_support.py`: Verifies state loading and saving handles both legacy and new formats correctly.
    *   (Implicitly verified via integration tests in Story 02).

