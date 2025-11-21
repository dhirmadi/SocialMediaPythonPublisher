<!-- docs_v2/08_Features/08_04_ChangeRequests/005/008_auto-view-anonymous-image-access.md -->

# Web Interface AUTO_VIEW Anonymous Image Access

**Feature ID:** 005  
**Change ID:** 005-008  
**Status:** Shipped  
**Date:** 2025-11-21  
**Author:** Evert  

## Summary

Introduce an `AUTO_VIEW` environment flag controlling whether the web UI may display images to unauthenticated / non-admin visitors, or only to logged-in admin users.  
When `AUTO_VIEW=true`, the root page may show random images and existing captions to any visitor (subject only to HTTP-level auth if configured); when `AUTO_VIEW=false`, images are only loaded and displayed after the operator has successfully logged into admin mode, preventing casual viewers from seeing image content.

## Problem Statement

The current Web Interface MVP and follow-up admin-mode changes gate **Analyze & caption**, **Publish**, and detailed status output behind admin mode, but image content itself is always retrievable via `GET /api/images/random`.  
On shared devices or semi-public deployments, this means that anyone who can reach the URL can see potentially sensitive images, even if they cannot trigger analysis or publishing.  
The repository needs a simple, environment-driven way to choose between:

- A **private operator-only** mode where images require admin login, and  
- A **viewer-friendly** mode where images may be safely browsed without logging in.

## Goals

- **G1:** Add an `AUTO_VIEW` flag (read from `.env`) that controls whether random images can be displayed without admin login.
- **G2:** When `AUTO_VIEW=false` (default), require that users be logged in as admin before any images are shown in the web UI.
- **G3:** When `AUTO_VIEW=true`, allow the existing “Next image” behavior to work for non-admin visitors, while still enforcing admin mode for analysis, publishing, keep/remove, and detailed operational status.
- **G4:** Make this behavior discoverable via a lightweight web configuration/feature flag endpoint so the UI can adapt without hard-coding assumptions.
- **G5:** Preserve existing CLI behavior and previously shipped web/admin behavior; this change must be strictly additive and backward compatible.

## Non-Goals

- Implementing per-user or per-role visibility rules beyond the single admin vs. anonymous distinction.
- Changing the semantics of admin mode, HTTP auth, or publisher enablement flags.
- Introducing database-backed user sessions or long-lived server-side state.
- Building a public gallery or multi-tenant viewer experience.

## User Stories

- **US1:** As an operator, I want to run the web UI in a strict private mode so that images are only visible after I explicitly log in as admin, even if someone else visits the URL on the same device.
- **US2:** As an operator, I want to run the web UI in a relaxed mode where trusted friends can casually browse images and captions without needing the admin password, while only I can analyze, publish, keep, or remove images.
- **US3:** As an operator, I want to control this behavior via a simple `.env` flag (`AUTO_VIEW`) so I can toggle between private and relaxed modes without code changes.

## Acceptance Criteria (BDD-style)

- **AC1 (Default private mode):**  
  Given `AUTO_VIEW` is unset or set to `false`, when an anonymous user opens `/` and the UI loads, then the page does **not** display any image until the admin has successfully logged in, and the “Next image” action either stays disabled or clearly indicates that admin login is required.
- **AC2 (Admin-gated images):**  
  Given `AUTO_VIEW=false` and a valid admin password configured, when the operator logs into admin mode, then “Next image” begins working and random images (plus existing captions) are displayed as today.
- **AC3 (Relaxed viewer mode):**  
  Given `AUTO_VIEW=true`, when an unauthenticated visitor opens `/` and clicks “Next image”, then a random image and its caption (if available) are displayed successfully, without requiring admin login, while analyze/publish/keep/remove actions still require admin mode.
- **AC4 (Config introspection):**  
  Given the web UI loads, when it calls the config/features endpoint, then it can determine whether `AUTO_VIEW` is enabled and adjust the initial button state and status messaging accordingly.
- **AC5 (Backward compatibility):**  
  Given a deployment that does not set `AUTO_VIEW`, when the app is upgraded, then behavior remains equivalent to `AUTO_VIEW=false` (private by default), and all existing tests for admin mode, analysis, publishing, and curation continue to pass.

## Technical Notes & Constraints

- `AUTO_VIEW` lives in `.env` (and Heroku config vars) and is parsed via the existing boolean parsing conventions used for other feature flags.
- The flag should be surfaced through an appropriate typed config (`FeaturesConfig` or `WebConfig`) and exposed via an HTTP endpoint (`/api/config/features` or similar) so the UI can query it instead of duplicating env logic in JavaScript.
- Server-side behavior for `GET /api/images/random` must respect `AUTO_VIEW`:
  - In private mode, it should reject unauthenticated / non-admin callers with a clear 403/401-style error.
  - In relaxed mode, it should allow the current behavior (subject to existing HTTP auth if enabled).
- Logging must use existing `log_json` helpers and avoid printing raw env values.

## Dependencies

- Parent feature request: `docs_v2/08_Features/08_01_Feature_Request/005_web-interface-mvp.md`
- Parent feature design: `docs_v2/08_Features/08_02_Feature_Design/005_web-interface-mvp_design.md`
- Existing change requests under Feature 005, especially:
  - `005-001` Web Interface Admin Controls
  - `005-003` Web UI admin visibility / responsive layout
  - `005-007` Feature toggle button visibility

## Risks & Mitigations

- **Risk:** Misconfiguration of `AUTO_VIEW` could unintentionally expose images to unauthenticated viewers.  
  **Mitigation:** Default to `AUTO_VIEW=false` (private), clearly document the flag, and ensure tests cover both modes.
- **Risk:** Inconsistent enforcement between backend and frontend could allow images to be fetched via API even when UI is locked down.  
  **Mitigation:** Enforce `AUTO_VIEW` at the API level for `GET /api/images/random` and treat UI behavior as an additional UX layer, not the primary guard.
- **Risk:** Interaction with existing HTTP auth and admin-mode cookies may be confusing.  
  **Mitigation:** Keep rules simple and clearly documented: admin mode is still required for mutating actions; `AUTO_VIEW` only controls whether random images are visible without admin.

## Implementation Summary

- Added `auto_view_enabled: bool` to `FeaturesConfig` and wired it via `load_application_config` using the `AUTO_VIEW` environment variable (parsed with `parse_bool_env`, defaulting to `False`/private mode).
- Updated `GET /api/images/random` in `publisher_v2.web.app` to:
  - Require admin mode (`require_admin`) when `auto_view_enabled` is `False` and admin is configured, emitting structured telemetry events for gated requests.
  - Return `503 Service Unavailable` when `AUTO_VIEW=false` but admin is not configured, failing closed without revealing images.
- Extended `/api/config/features` to include `auto_view_enabled` so the web UI can query the server-side setting.
- Updated `publisher_v2.web.templates.index.html` to:
  - Load `auto_view_enabled` from `/api/config/features`.
  - Gate the initial random-image load and “Next image” button based on `AUTO_VIEW` + admin state.
  - Show clear status messages (“Admin mode required to view images.”) and a simple “Private mode”/“Viewer mode” indicator.

## Testing Summary

- **Config & loader:** Existing config loader tests extended to remain green with the new `auto_view_enabled` flag, and a targeted test ensures `.env` contents do not interfere with default feature-toggle semantics.
- **Web API:** New integration tests in `publisher_v2/tests/web_integration/test_web_auto_view.py` cover:
  - AUTO_VIEW disabled + admin configured → non-admin sees 403; admin can fetch images (with Dropbox calls stubbed).
  - AUTO_VIEW disabled + admin unconfigured → 503 fail-closed.
  - AUTO_VIEW enabled → anonymous clients can call `/api/images/random` successfully.
- **Feature endpoint:** `/api/config/features` tests (`test_publishers_endpoint.py`) updated to assert the presence and default value of `auto_view_enabled`, and to ensure feature flags remain booleans.
- **Telemetry:** End-to-end performance telemetry test updated to accept admin-gated statuses (403/503) while still asserting that `web_random_image*` telemetry events are emitted with timing fields.

## Artifacts

- Change Request (this document): `docs_v2/08_Features/08_04_ChangeRequests/005/008_auto-view-anonymous-image-access.md`  
- Change Design: `docs_v2/08_Features/08_04_ChangeRequests/005/008_design.md`  
- Story Plan: `docs_v2/08_Features/08_04_ChangeRequests/005/008_plan.yaml`  
- Code:
  - `publisher_v2/src/publisher_v2/config/schema.py`
  - `publisher_v2/src/publisher_v2/config/loader.py`
  - `publisher_v2/src/publisher_v2/web/app.py`
  - `publisher_v2/src/publisher_v2/web/templates/index.html`
- Tests:
  - `publisher_v2/tests/web_integration/test_web_auto_view.py`
  - `publisher_v2/tests/web/test_publishers_endpoint.py`
  - `publisher_v2/tests/test_config_loader.py`
  - `publisher_v2/tests/test_e2e_performance_telemetry.py`



