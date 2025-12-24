<!-- docs_v2/08_Epics/08_01_Feature_Request/010_keep-remove-curation.md -->

# Keep/Remove Curation Controls

**ID:** 010  
**Name:** keep-remove-curation  
**Status:** Shipped  
**Date:** 2025-11-21  
**Author:** User Request  

## Summary
Add two new admin-only **Keep** and **Remove** curation actions to the V2 web UI and core workflow.  
When viewing a single image in the web interface (same context as **Analyze** and **Publish**), an authenticated admin can choose:
- **Keep** → move the current image and its sidecars/metadata into a configurable `folder_keep` subfolder under the main Dropbox image folder.
- **Remove** → move the current image and its sidecars/metadata into a configurable `folder_remove` subfolder under the main Dropbox image folder (with backward-compatible support for existing `folder_reject` configs).
These actions must be fully integrated into the existing storage workflow, respect preview/dry-run safety guarantees, and be independently toggleable via feature flags and configuration.

## Problem Statement
Today, when reviewing candidate images in the V2 web interface, the only admin actions are **Analyze & caption** and **Publish**.  
There is no quick way to curate images that should be **kept for later** (e.g., approved for a future posting batch) or **removed from the current candidate pool** without publishing or manually moving files in Dropbox.  
This makes it hard to:
- Maintain a clean “to post” folder without manual Dropbox operations.
- Explicitly mark images as “keep for later” vs. “remove from current selection” when previewing from the web UI.
- Ensure removed images are not re-selected by the main workflow in the same or future runs.

The existing archive behavior moves successfully published images into an `archive` subfolder, and there is a legacy `folder_reject` in some configs, but there is no first-class, operator-facing curation mechanism exposed through the web interface.

## Goals
- Add two admin-only, web-visible curation actions for the currently displayed image:
  - **Keep** → move image + sidecars into a configurable `folder_keep` subfolder.
  - **Remove** → move image + sidecars into a configurable `folder_remove` subfolder (honoring existing `folder_reject` when present).
- Ensure both actions:
  - Use existing Dropbox/storage abstractions and server-side moves.
  - Move all relevant sidecars/metadata files along with the image using the same patterns as archive moves.
  - Are gated behind feature flags and config so they can be enabled/disabled independently of Analyze/Publish.
- Expose Keep/Remove via new admin-only buttons in the web UI next to **Analyze & caption** and **Publish**.
- Make target folders configurable via INI `[Dropbox]` section and overridable from `.env`, and document them in `CONFIGURATION.md`.
- Maintain preview/dry-run safety guarantees: in preview/dry modes, do not perform Dropbox moves; instead, log/preview what would happen.
- Preserve full backward compatibility when the feature is disabled or not configured.

## Non-Goals
- Introducing any destructive delete operation; images are always moved, never deleted.
- Implementing multi-step or batch curation workflows (e.g., queues, bulk actions, or multi-image selection).
- Changing how Analyze or Publish work beyond integrating with new curation semantics where necessary.
- Adding new storage providers or changing Dropbox as the source of truth.
- Introducing new persistent databases or changing the sidecar file formats.
- Providing per-platform or per-publisher-specific curation rules (Keep/Remove operate at the image level only).

## Users & Stakeholders
- **Primary users**
  - Solo creator/administrator using the V2 web UI to review and manage images.
- **Stakeholders**
  - Repository maintainer(s) for Social Media Publisher V2.
  - Future small teams using the web UI who need quick “approve/keep” vs “remove” controls.

## User Stories
- As an admin reviewing images in the web UI, I want a **Keep** button so I can move an image I like (and its metadata) into a dedicated “keep” subfolder without publishing it yet, keeping my main folder clean.
- As an admin reviewing images in the web UI, I want a **Remove** button so I can move an image (and its sidecars) into a dedicated “remove/reject” subfolder, ensuring it is no longer considered by the main workflow.
- As an admin, I want Keep/Remove to use the same Dropbox-sidecar handling patterns as archive, so I do not lose caption/analysis metadata when curating.
- As an admin, I want Keep/Remove to be available only when I am authenticated and in admin mode, so non-admin users cannot curate or disrupt the candidate pool.
- As an operator, I want configurable `folder_keep` and `folder_remove` settings in my INI and `.env`, so I can tailor curation folders per environment (e.g., staging vs. production).
- As an operator, I want the system to remain safe in preview/dry modes, so Keep/Remove actions only log or preview what would happen and never move files while I’m testing.
- As an operator with existing configs using `folder_reject`, I want the new Remove behavior to work without breaking my current setup, so my existing “reject” folder is still honored.

## Acceptance Criteria (BDD-style)
- **Keep behavior (normal mode)**
  - Given the web UI shows an image and I am an authenticated admin, and `folder_keep` is configured, when I click **Keep**, then the application uses the existing Dropbox/storage abstraction to perform a server-side move of the image from `[Dropbox].image_folder` into `[Dropbox].image_folder/[Dropbox].folder_keep`, and any associated sidecar/metadata files (caption JSON, SD caption `.txt`, extended analysis JSON, etc.) are moved along with the image following the same patterns as archive moves.
  - Given Keep succeeds for the current image, when the request completes, then the web UI displays a clear confirmation (e.g., “Moved to keep: {filename} → {folder_keep}”) and advances to the next image in the current selection.

- **Remove behavior (normal mode)**
  - Given the web UI shows an image and I am an authenticated admin, and `[Dropbox].folder_remove` (or legacy `folder_reject`) is configured, when I click **Remove**, then the application performs a server-side move of the image and associated sidecars from `[Dropbox].image_folder` into `[Dropbox].image_folder/[Dropbox].folder_remove` (or `[Dropbox].folder_reject`), and the removed image is no longer eligible for selection from the main image folder in subsequent runs.
  - Given Remove succeeds, when the request completes, then the web UI clearly indicates that the image was **moved** (not deleted) and advances to the next image.

- **Preview/dry-run safety**
  - Given the core workflow is running in preview mode (`--preview`) or dry-publish mode, when a Keep or Remove action is invoked through the orchestrator-layer API, then no Dropbox moves occur; instead, the system uses existing preview utilities to print/log a human-readable description of what would have happened (e.g., “Would move {image} → {folder_keep}”), and no state, sidecars, or archives are mutated.

- **Admin-only and feature toggles**
  - Given I am not authenticated or not in admin mode, when I load the web UI, then I do not see the Keep or Remove buttons, and I cannot successfully call any Keep/Remove endpoints (they must be protected by the same HTTP auth + admin cookie checks as Analyze and Publish).
  - Given the Keep/Remove feature (or its individual Keep/Remove sub-flags) is disabled via feature flags or not configured, when I open the web UI, then it behaves exactly as today: no Keep/Remove buttons are visible and no new endpoints are callable.

- **Configuration and env integration**
  - Given `[Dropbox].folder_keep` and `[Dropbox].folder_remove` keys are present in the INI file, when the config loader runs, then these values are validated and made available via the typed `DropboxConfig`.
  - Given `.env` contains `folder_keep` and/or `folder_remove`, when the config loader runs, then these values override the INI values and feed `[Dropbox].folder_keep` / `[Dropbox].folder_remove` in `DropboxConfig`.
  - Given an existing config that uses `[Dropbox].folder_reject` and no explicit `folder_remove`, when the config loader runs, then `folder_remove` is populated from `folder_reject` to preserve current behavior.

## UX / Content Requirements
- Web UI:
  - Two new admin-only buttons **Keep** and **Remove** appear alongside **Analyze & caption** and **Publish** only when:
    - The user is authenticated and in admin mode, and
    - The corresponding feature flag(s) and folder configuration(s) are active.
  - After a successful Keep or Remove action, the UI:
    - Shows a concise status message indicating the action, target folder, and filename.
    - Fetches and displays the next image in the same way as “Next image”.
  - For Remove, text should emphasize that the image was moved, not deleted (e.g., “Moved to remove folder; not deleted”).
- Error states:
  - If folders are not configured or the feature is disabled, the UI should either hide the buttons or show a clear, admin-only error message when actions are invoked.
  - Errors from Dropbox moves should be surfaced as clear, non-technical status messages while maintaining detailed structured logs server-side.

## Technical Requirements
- Configuration:
  - Extend `DropboxConfig` and the config loader to support:
    - `folder_keep` (optional string; relative subfolder name under `image_folder`).
    - `folder_remove` (optional string; relative subfolder name under `image_folder`), with backward-compatible aliasing from existing `folder_reject`.
  - Support `.env` variables `folder_keep` and `folder_remove` that override INI values for the corresponding fields.
  - Update `docs_v2/05_Configuration/CONFIGURATION.md` to document the new `[Dropbox]` keys and `.env` variables.
- Workflow / storage:
  - Extend `DropboxStorage` with a reusable “move image + sidecars” helper that:
    - Performs server-side Dropbox folder creation when needed.
    - Moves the primary image and all relevant sidecar/metadata files in a single logical operation.
    - Is reused by archive, Keep, and Remove behaviors where appropriate.
  - Introduce orchestrator-level curation entry points that:
    - Accept a filename and a curation action (Keep or Remove).
    - Use the storage move helper and configuration to determine destination.
    - Respect preview/dry flags by delegating to preview utilities instead of performing real moves.
- Web layer:
  - Add new admin-only FastAPI endpoints for:
    - `POST /api/images/{filename}/keep`
    - `POST /api/images/{filename}/remove`
    - Both must be protected by `require_auth` and `require_admin` and return a small, typed response summarizing the action.
  - Add corresponding methods to `WebImageService` that:
    - Call into the orchestrator/storage layer.
    - Enforce feature flags and configuration presence.
  - Update the HTML template and JS to:
    - Render Keep/Remove buttons only for admins.
    - Query feature configuration (similar to existing feature toggles) to hide buttons when disabled.
    - Advance to the next image on successful curation.

## Dependencies
- Existing configuration system and schema (`publisher_v2.config.loader`, `publisher_v2.config.schema`).
- Existing Dropbox storage abstraction (`publisher_v2.services.storage.DropboxStorage`) and archive/sidecar movement patterns.
- Workflow orchestrator (`publisher_v2.core.workflow.WorkflowOrchestrator`) for preview/dry semantics and centralized orchestration.
- Web app and service layer (`publisher_v2.web.app`, `publisher_v2.web.service`) plus admin/auth helpers (`publisher_v2.web.auth`).
- Existing preview utilities (`publisher_v2.utils.preview`) for non-destructive preview output.

## Risks & Mitigations
- **Risk:** Misconfiguration of keep/remove folders could result in images being moved to unexpected paths.  
  **Mitigation:** Validate configuration, document clearly that folders are relative to `[Dropbox].image_folder`, and surface clear error messages/logs when misconfigured.

- **Risk:** Keep/Remove might accidentally perform real Dropbox moves during preview/dry testing.  
  **Mitigation:** Route curation actions through orchestrator APIs that explicitly check preview/dry flags and delegate to preview utilities instead of storage moves in those modes; add tests for preview/dry behavior.

- **Risk:** Non-admin users could see or trigger curation actions.  
  **Mitigation:** Reuse existing HTTP auth + admin cookie checks; hide Keep/Remove buttons entirely for non-admins and return 401/403 for unauthorized calls.

- **Risk:** Backward compatibility with existing configs using `folder_reject` could be broken.  
  **Mitigation:** Treat `folder_reject` as a backward-compatible alias for `folder_remove` when the latter is not set; add tests to cover this mapping.

## Open Questions
- Should Keep/Remove actions update any local deduplication state (hashes) beyond moving the file out of the main folder, or is “no longer present in `image_folder`” sufficient? (Initial assumption: moving out of `image_folder` is sufficient.)
- Should Keep/Remove be exposed via CLI in addition to the web UI, or remain web-only for now? (Initial assumption: web-only curation in this feature, CLI integration can be a future extension.)
- Should there be separate feature flags for Keep vs Remove, or a single combined curation flag? (Initial proposal: separate `keep_enabled` and `remove_enabled` flags for maximum flexibility.)


