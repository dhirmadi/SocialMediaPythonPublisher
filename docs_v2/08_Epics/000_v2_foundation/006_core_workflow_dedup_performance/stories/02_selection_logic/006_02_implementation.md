# Implementation Story: 02_selection_logic

This story covers the workflow logic updates defined in 006_02_plan.yaml.

## Context
With the infrastructure in place, the core `WorkflowOrchestrator` needed to be refactored to use metadata for selection, avoiding the expensive "download-then-hash" loop for known duplicates.

## Plan Execution

### 1. Workflow Orchestrator
*   **Selection Logic**: Refactored `WorkflowOrchestrator.execute` in `publisher_v2/core/workflow.py`.
    *   **Step 1**: Retrieve `images_with_hashes` from storage.
    *   **Step 2**: Load `posted_content_hashes` from state.
    *   **Step 3**: Filter candidates locally. If a candidate's hash is known, it is skipped.
    *   **Step 4**: If no candidates remain, return "No new images" error immediately. **Result**: Zero downloads for full folders.
    *   **Step 5**: If a candidate is selected, download *only* that image to compute its SHA256 (needed for legacy state and non-Dropbox dedup).
*   **Persistence**: Updated the success path to call `save_posted_content_hash` in addition to `save_posted_hash` when archiving.

## Verification
*   **Tests**:
    *   `test_dedup_selection.py`: Verifies the "No new images" path works correctly.
    *   `test_workflow_metadata_selection.py`:
        *   Mocks `list_images_with_hashes` to return known duplicates.
        *   Asserts `download_image` is NOT called for duplicates.
        *   Asserts state is updated correctly on success.

