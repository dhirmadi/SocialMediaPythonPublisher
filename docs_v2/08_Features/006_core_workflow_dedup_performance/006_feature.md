<!-- docs_v2/08_Features/08_01_Feature_Request/006_core-workflow-dedup-performance.md -->

# Core Workflow Dedup Performance

**ID:** 006  
**Name:** core-workflow-dedup-performance  
**Status:** Implemented  
**Date:** 2025-11-20  
**Author:** Architecture Team  

## Summary
The core workflow previously performed image de-duplication by downloading candidate images from Dropbox and computing local hashes, which did not scale efficiently as the image library grew.  
This feature introduces a revised deduplication and selection strategy that leverages Dropbox-native `content_hash` metadata and minimizes network I/O while keeping existing behavior and sidecar semantics intact.  
The outcome is a faster, more predictable image selection phase that still respects the "do not repost the same image" guarantee, backed by tests and documented architecture updates.

## Problem Statement
Today, `WorkflowOrchestrator` selects an image to post by listing images from the configured Dropbox folder and then downloading them one by one to compute SHA256 hashes, skipping those that already appear in the local `posted` state.  
For large folders or many previously posted images, this results in unnecessary downloads, increased latency, and higher bandwidth usage, even when the final result is "no new images".  
There is no feature-level specification for a more efficient selection and dedup approach, making performance-sensitive changes to this area ad hoc and undocumented.

## Goals
- Reduce the number of full image downloads required during selection while preserving dedup correctness.  
- Use Dropbox metadata (e.g., `content_hash`) to perform de-duplication as early as possible in the workflow.  
- Keep behavior backward-compatible with existing CLI flags, preview/dry semantics, and sidecar/archive handling.

## Non-Goals
- Changing the semantics of what counts as a "duplicate" from a user perspective.  
- Introducing new persistent data stores beyond the existing filesystem-based posted-hash state.  
- Modifying publishers, caption/sidecar generation, or web interface behavior (those are covered by other features/CRs).

## Users & Stakeholders
- Primary users: CLI operators running the V2 workflow for daily or batch publishing.  
- Stakeholders: Architecture team, maintainers responsible for performance and reliability, operations/DevOps teams monitoring runtime behavior.

## User Stories
- As an operator, I want the CLI workflow to select a new image quickly even when the Dropbox folder contains many previously posted files, so that routine runs remain fast over time.  
- As a maintainer, I want de-dup logic to use efficient metadata-based checks wherever possible, so that we minimize unnecessary Dropbox downloads.  
- As an architect, I want a documented and testable selection/dedup strategy, so that future optimizations can be made safely.

## Acceptance Criteria (BDD-style)
- Given a Dropbox folder containing a mix of new and already-posted images, when the workflow runs, then it must avoid downloading more than a small number of images (ideally one) before selecting a new, unposted image.  
- Given a Dropbox folder where all images have already been posted, when the workflow runs, then it must still correctly report "no new images" without downloading every file in the folder.  
- Given the posted-hash state and Dropbox contents are consistent, when the workflow runs multiple times, then it must not select the same image twice until the state is cleared or reset.  
- Given existing tests and behaviors around preview, dry runs, and archival, when this feature is implemented, then all of those behaviors must continue to pass unchanged.

## UX / Content Requirements
- CLI behavior and flags remain unchanged; any performance improvement is transparent to users.  
- Error messages related to "no images" or "no new images" must remain clear and consistent with current wording.  
- Documentation (README and docs_v2) should briefly note that image selection performance has been improved via metadata-based deduplication.

## Technical Constraints & Assumptions
- The feature must continue to use Dropbox as the source of truth for images and sidecars.  
- Dropbox's `content_hash` or similar metadata is assumed to be stable and suitable for deduplication across runs.  
- Implementation must remain compatible with Python 3.9–3.12 and reuse existing configuration and state utilities.  
- No new external dependencies (databases, message queues) may be introduced as part of this feature.  
- Changes should be localized primarily to `publisher_v2/core/workflow.py`, `publisher_v2/services/storage.py`, and `publisher_v2/utils/state.py`, reusing existing patterns in those modules.

## Dependencies & Integrations
- Dropbox SDK and `DropboxStorage` abstraction for listing images and retrieving metadata.  
- `WorkflowOrchestrator` and `utils.state` for integrating metadata-based dedup into selection and posted-hash management.  
- Existing logging and error-handling mechanisms for reporting selection outcomes.

## Data Model / Schema
- The posted-hash state file has been extended to optionally store Dropbox-level content hashes alongside existing SHA256 hashes while preserving legacy formats.  
- No changes to core domain models were required; content hashes are handled by storage and state utilities.  
- The evolution is backward-compatible and preserves existing state files, treating them as authoritative for previously posted images.

## Security / Privacy / Compliance
- No new categories of data are stored beyond hashes/identifiers already present in Dropbox and local state.  
- Content hashes are non-sensitive and must not be treated as secrets.  
- All existing PG-13 and content-safety requirements remain enforced elsewhere in the pipeline.

## Performance & SLOs
- Image selection (including dedup) should typically complete in under a few seconds, even for folders with many files and a high proportion of already-posted images.  
- The number of full image downloads per run should be minimized (ideally O(1) for successful selection, O(1)–O(k) for "no new images").  
- Error rates must remain within existing budgets; this feature must not increase timeouts or failure rates.

## Observability
- Metrics: count of images considered vs. downloaded during selection; count of "no new images" outcomes.  
- Logs & events: structured events capturing selection flow (e.g., `image_selection_start`, `image_selection_complete`, with counts and timing).  
- Dashboards/alerts: TODO; minimal log-based monitoring may be sufficient initially.

## Risks & Mitigations
- Relying on Dropbox metadata could introduce subtle drift if content_hash semantics change — Mitigation: document assumptions and maintain a migration path back to local hashing if needed.  
- Migration of posted-hash state could lead to duplicates if done incorrectly — Mitigation: provide careful migration logic and tests; consider treating old and new hashes equivalently during a transition period.  
- Edge cases with partially uploaded or renamed files — Mitigation: rely on Dropbox APIs for consistent listing and metadata; handle errors and unexpected states gracefully.

## Open Questions
- Should we store both local SHA256 and Dropbox content_hash in posted state for a period of time? — Proposed answer: likely yes for a safe transition.  
- How should we handle folders with extremely large numbers of images (tens of thousands)? — Proposed answer: TODO; may need additional paging or sampling strategies.  
- Do we need a manual "reset" mechanism for posted-hash state beyond what already exists? — Proposed answer: TODO; evaluate operator needs.

## Milestones
- M1: Design & validation of metadata-based dedup approach (including state migration plan).  
- M2: Implementation of new selection logic and posted-hash handling, with unit and integration tests.  
- M3: Performance validation and rollout, including documentation updates and monitoring adjustments.

## Definition of Done
- New dedup/selection logic is implemented and covered by tests for both normal and edge cases.  
- Performance of image selection is measurably improved in representative scenarios.  
- All existing CLI behaviors, flags, and outputs remain backward-compatible.  
- Documentation and any relevant diagrams are updated to reflect the new selection strategy and the use of Dropbox `content_hash` in selection and state.

## Appendix: Source Synopsis
- Core workflow performance review identified image selection and dedup as a major latency source due to repeated Dropbox downloads and hashing.  
- Architecture guidelines emphasize Dropbox as source of truth and avoiding new data stores.  
- Earlier discussions proposed using Dropbox `content_hash` and improving selection complexity while retaining existing sidecar and posting semantics.


