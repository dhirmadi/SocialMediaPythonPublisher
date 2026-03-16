# PUB-006: Core Workflow Dedup Performance

| Field | Value |
|-------|-------|
| **ID** | PUB-006 |
| **Category** | Foundation |
| **Priority** | INF |
| **Effort** | M |
| **Status** | Done |
| **Dependencies** | — |

## Problem

The core workflow performed image de-duplication by downloading candidate images from Dropbox and computing local hashes, which did not scale as the image library grew. For large folders or many previously posted images, this resulted in unnecessary downloads, increased latency, and higher bandwidth usage, even when the final result was "no new images". There was no feature-level specification for a more efficient selection and dedup approach.

## Desired Outcome

A revised deduplication and selection strategy that leverages Dropbox-native `content_hash` metadata and minimizes network I/O while keeping existing behavior and sidecar semantics intact. The outcome is a faster, more predictable image selection phase that still respects the "do not repost the same image" guarantee, backed by tests and documented architecture updates.

## Scope

- Use Dropbox `content_hash` metadata for early deduplication
- Extend posted-hash state to store Dropbox content hashes alongside legacy SHA256
- Refactor `WorkflowOrchestrator` to filter candidates locally before downloading
- Download only the selected image (for SHA256 and legacy state)
- Zero downloads when all images are already posted
- Backward-compatible with existing CLI flags, preview/dry semantics, sidecar/archive handling

## Acceptance Criteria

- AC1: Given a Dropbox folder containing a mix of new and already-posted images, when the workflow runs, then it must avoid downloading more than a small number of images (ideally one) before selecting a new, unposted image
- AC2: Given a Dropbox folder where all images have already been posted, when the workflow runs, then it must still correctly report "no new images" without downloading every file in the folder
- AC3: Given the posted-hash state and Dropbox contents are consistent, when the workflow runs multiple times, then it must not select the same image twice until the state is cleared or reset
- AC4: Given existing tests and behaviors around preview, dry runs, and archival, when this feature is implemented, then all of those behaviors must continue to pass unchanged

## Implementation Notes

- **Storage**: Added `list_images_with_hashes` to `DropboxStorage` — calls `files_list_folder`, parses `FileMetadata` for `name` and `content_hash`, returns `(filename, hash)` tuples
- **State**: `load_posted_content_hashes()` and `save_posted_content_hash()` in `utils/state.py`; new `dropbox_content_hashes` key in `posted.json`; backward-compatible with legacy format
- **Workflow**: Step 1 retrieve images_with_hashes; Step 2 load posted_content_hashes; Step 3 filter locally; Step 4 return "no new images" immediately if no candidates; Step 5 download only selected image for SHA256
- **Tests**: `test_dedup_selection.py`, `test_workflow_metadata_selection.py`, `test_utils_support.py`
- Localized to `workflow.py`, `storage.py`, `state.py`

## Related

- [Original feature doc](../../08_Epics/000_v2_foundation/006_core_workflow_dedup_performance/006_feature.md) — full historical detail
