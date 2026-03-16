# PUB-023: Storage Protocol Extraction

| Field | Value |
|-------|-------|
| **ID** | PUB-023 |
| **Category** | Foundation |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Not Started |
| **Dependencies** | PUB-015 |

## Problem

The publisher's storage contract is implicit. `DropboxStorage` is the only implementation, and all consumers (`WorkflowOrchestrator`, `WebImageService`, `generate_and_upload_sidecar`) type-hint it concretely. There is no formal `Protocol` or base class — the interface is defined only by convention and test dummies. This makes it impossible to introduce a second storage backend without touching every consumer, and it increases the risk of interface drift.

## Desired Outcome

A formal `StorageProtocol` (Python `Protocol` class) that captures the ~12 methods the publisher consumes. All consumers type-hint the protocol instead of `DropboxStorage`. `DropboxStorage` implements the protocol. No behavior change — this is a pure refactor that establishes the extension point for alternative storage backends.

## Scope

- Define `StorageProtocol` in `publisher_v2/services/storage.py` (or a new `storage_protocol.py`) with all methods currently consumed by `WorkflowOrchestrator`, `WebImageService`, and sidecar utilities
- Replace `DropboxStorage` type hints with `StorageProtocol` in:
  - `publisher_v2/core/workflow.py` (`WorkflowOrchestrator.__init__`)
  - `publisher_v2/web/service.py` (`WebImageService`)
  - `publisher_v2/utils/captions.py` (sidecar generation)
  - Any other direct references
- Ensure `DropboxStorage` satisfies the protocol (mypy structural subtyping)
- Extract Dropbox-specific concerns (e.g., `content_hash`, `ThumbnailSize`/`ThumbnailFormat` enums) so the protocol uses generic equivalents
- Update test dummies/mocks to implement the protocol

## Non-Goals

- No new storage backend (that is PUB-024)
- No config changes — storage selection remains Dropbox-only
- No behavior change — all existing tests must pass unchanged

## Acceptance Criteria

- AC1: A `StorageProtocol` class exists defining all methods consumed by the workflow, web service, and sidecar utilities
- AC2: `WorkflowOrchestrator`, `WebImageService`, and sidecar functions accept `StorageProtocol` (not `DropboxStorage`) in their type signatures
- AC3: `DropboxStorage` satisfies `StorageProtocol` as verified by mypy (structural subtyping)
- AC4: The protocol uses generic types for thumbnails (e.g., `str` enum values or a protocol-level `ThumbnailSize`) rather than Dropbox SDK types
- AC5: All existing tests pass without modification (pure refactor)
- AC6: `hasattr`-based feature detection (e.g., `list_images_with_hashes`) is replaced by protocol-level optional methods or a capability flag
- AC7: Zero new lint or type-check violations

## Implementation Notes

- Use `typing.Protocol` (runtime_checkable optional) for structural subtyping — no need for `DropboxStorage` to explicitly inherit from it
- The `list_images_with_hashes` conditional (`hasattr` check in `workflow.py`) should become a protocol method with a default or a separate `HashableStorage` protocol
- `ThumbnailSize` and `ThumbnailFormat` are Dropbox SDK enums; the protocol should define its own enum or accept strings, with `DropboxStorage` mapping internally
- Keep `StorageError` as the common exception type across all implementations

## Related

- [PUB-015: Cloud Storage Adapter (Dropbox)](archive/PUB-015_cloud-storage-dropbox.md) — the current Dropbox implementation
- [PUB-024: Managed Storage Adapter](PUB-024_managed-storage-adapter.md) — the follow-on item this unblocks
