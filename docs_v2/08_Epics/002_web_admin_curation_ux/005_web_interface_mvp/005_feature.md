<!-- 08_01_Feature_Requests/005_web-interface-mvp.md -->

# Web Interface MVP

**ID:** 005  
**Name:** web-interface-mvp  
**Status:** Shipped  
**Date:** 2025-11-19  
**Author:** Evert  

## Summary
Introduce a minimal web interface on top of the existing Social Media Publisher V2 so it can be accessed and controlled from a phone, without changing core behaviors or adding new data stores.  
The MVP will expose a simple browser-based UI that lets the (single) operator view a random image from the configured Dropbox folder, trigger AI analysis/captioning, and publish the image using the existing publishers.  
All state continues to live in Dropbox and sidecar files; no MongoDB, streams, or multi-tenant capabilities are introduced in this phase.  
The solution must be deployable as a single Heroku web app using the current configuration and async patterns.

## Problem Statement
Today the system can only be operated via a CLI command on a machine with terminal access, which is inconvenient when the user wants to run workflows from a mobile device.  
This friction makes it harder to casually preview images, trigger AI analysis/caption generation, and publish content while away from the development machine.  
The existing architecture already encapsulates image selection, AI processing, sidecar creation, and publishing, but there is no thin, easy-to-use web layer exposing those capabilities.  
We need a simple, secure-enough web UI that reuses the current logic, avoids extra infrastructure (like new databases or services), and can be deployed to Heroku.

## Goals
- Provide a minimal web UI accessible from a phone that can:
  - Show a random image from the configured Dropbox folder.
  - Trigger AI analysis and caption/sd_caption generation for that image.
  - Trigger publishing of that image to configured channels.
- Reuse the existing V2 orchestration, AI, storage, and sidecar mechanisms without changing their core semantics.
- Deploy the application as a single Heroku web app (one container) with configuration via environment variables and INI files.
- Keep the architecture simple and extensible so future features (streams, MongoDB, richer roles) can be layered on later without a rewrite.

## Non-Goals
- Implementing multi-stream or multi-folder concepts (all operations target the single configured image folder).
- Adding MongoDB or any new persistent database for image metadata or streams.
- Building a full user management system or complex role-based access control; MVP assumes a single operator and, optionally, a lightweight protection (e.g., shared password).
- Implementing a public gallery, viewer accounts, or fine-grained permissions beyond "operator vs. anonymous".
- Replacing or breaking existing CLI workflows; CLI remains supported and unchanged in behavior.

## Users & Stakeholders
- Primary users:
  - Solo creator/administrator operating the publisher from phone or desktop browser.
- Stakeholders:
  - Repository maintainer(s) for Social Media Publisher V2.
  - Future small teams or collaborators who may use the web UI once it stabilizes.

## User Stories
- As an administrator, I want to open a URL on my phone and see a random image from my configured Dropbox folder, so that I can quickly review candidate content without using a terminal.
- As an administrator, I want to tap a button to run AI analysis and caption/sd_caption generation for the currently shown image, so that I can enrich it with metadata and captions using the existing AI logic.
- As an administrator, I want to tap a button to publish the currently shown image to the configured platforms, so that I can trigger the full workflow (including archiving and sidecar updates) from the web UI.
- As an administrator, I want the web UI actions to respect the existing dry/preview/debug behaviors, so that I do not accidentally publish when I intend to preview.
- As an administrator, I want a minimal safeguard (e.g., simple auth or secret) to prevent casual unauthorized users from triggering analysis or publishing actions.

## Acceptance Criteria (BDD-style)
- Given the app is deployed on Heroku with a valid config INI and Dropbox/OpenAI credentials, when I open the root URL (`/`) in a browser, then I see a simple page that can display a single image and buttons for "Next image", "Analyze & caption", and "Publish".
- Given there is at least one eligible image in the configured Dropbox folder, when I click "Next image", then the backend selects a random image from that folder (respecting existing selection/dedup rules where applicable) and the UI updates to show that image.
- Given a currently displayed image without existing AI sidecar data, when I click "Analyze & caption", then the backend runs the existing AI analysis and caption/sd_caption generation logic and writes/overwrites the sidecar file, and the UI displays the resulting caption (and optionally key analysis fields) without errors.
- Given a currently displayed image with a sidecar already present, when I click "Analyze & caption", then the sidecar is updated with the new analysis/caption content and the UI reflects the updated caption.
- Given a currently displayed image and valid platform configurations, when I click "Publish", then the backend invokes the existing publishers, behaves exactly like the current non-web workflow (including archiving and sidecar movement on success), and the UI shows a clear success/failure summary per platform.
- Given the system is configured in a dry/preview/debug mode equivalent, when I use the web UI actions, then no external publishing or archiving occurs and the behavior matches the existing CLI semantics for those modes.
- Given the application is configured with an optional simple protection mechanism (e.g., shared admin secret), when an unauthenticated user accesses `/`, then they can at most see a non-interactive or limited view (configurable) and cannot trigger analysis/publish actions; when a user provides the correct secret, then they can use all admin actions.
- Given any error occurs during Dropbox, AI, or publishing operations, when I use the web UI, then I see a clear error message and the server logs a structured error event without exposing secrets.

## UX / Content Requirements
- Single-page, mobile-friendly layout with:
  - Image viewer area that scales within phone viewport (no horizontal scrolling).
  - Buttons for "Next image", "Analyze & caption", and "Publish" clearly separated and touch-friendly.
  - A caption/metadata area showing at least the generated caption; optionally sd_caption and a few key analysis attributes (e.g., mood, tags count).
- Minimal styling is acceptable (simple CSS), but must remain readable on dark and light phone themes.
- Clear confirmation text after actions:
  - After analysis: "Analysis complete; caption generated."
  - After publish: "Published to: [list of successful platforms]; failures: [if any]."
- Error states must be clearly surfaced (e.g., "No images found", "AI error", "Publishing failed to Telegram") with non-technical text.
- Accessibility basics:
  - Buttons with descriptive labels.
  - Alt text for images derived from the AI description if available, else a generic fallback.
- Localization is not required in MVP; English copy is sufficient.

## Technical Constraints & Assumptions
- Backend remains Python 3.9–3.12 compatible. Documentation examples standardize on **uv**, with Poetry supported via `pyproject.toml`.
- Web server is implemented using a lightweight Python web framework (e.g., FastAPI/Starlette/Flask) integrated into the `publisher_v2` package without altering current CLI entrypoint behavior.
- Deployment target is Heroku (or Heroku-like) as a single web dyno:
  - `Procfile` defines a `web` process using an ASGI server like `uvicorn`.
  - Config INI path and secret keys are provided via environment variables.
- No new databases are introduced; image metadata and captions live in sidecar files in Dropbox as today.
- The existing `WorkflowOrchestrator`, `DropboxStorage`, `AIService`, publishers, and sidecar builders remain the primary implementation of business logic; the web layer should call into these rather than duplicating logic.
- The CLI interface (arguments, behavior) must remain backward compatible.
- Async patterns must be preserved; avoid introducing blocking calls on the main event loop.

## Dependencies & Integrations
- Dropbox: continues to be the single storage provider for images and sidecar files in this MVP.
- OpenAI: same models and configuration as in V2 for analysis and caption generation.
- Existing publishers: Telegram, Email, Instagram classes are reused for web-triggered publishing.
- Heroku: environment for deployment, including config vars for secrets and config paths.
- No new third-party identity provider is required; any simple protection is implemented locally (e.g., basic auth or pre-shared token).

## Data Model / Schema
- No new persistent data model beyond:
  - Existing sidecar text format containing sd_caption and metadata.
- Any additional minimal state needed by the web layer (e.g., last-selected image) can be:
  - Recomputed on each request, or
  - Stored transiently in memory (non-persistent, safe under dyno restarts).
- Future extension points:
  - Streams and MongoDB-based metadata storage are explicitly left for later feature requests and must not be implied by this change.

## Security / Privacy / Compliance
- The web UI must not expose Dropbox paths, raw tokens, or OpenAI keys in responses or logs.
- Optional lightweight access control (e.g., shared admin secret or HTTP basic auth) should protect analysis and publishing actions from unauthorized use.
- All logs must continue to use structured logging and avoid including secrets or sensitive credentials.
- Content rules remain PG-13/fine-art style as already enforced by prompts; this feature does not relax any existing safety logic.
- The Heroku app must use HTTPS (via the platform) for all client-facing traffic.

## Performance & SLOs
- Web interactions should complete within:
  - P95 < 5s for "Next image" (dominated by Dropbox listing and selection).
  - P95 < 20s for "Analyze & caption" (dominated by OpenAI latency).
  - P95 < 30s for "Publish" (dominated by external platforms).
- Error rate for web-triggered flows should be no higher than existing CLI-triggered flows under similar conditions.
- Throughput expectations are low (single user), so horizontal scaling is not required in MVP.

## Observability
- Metrics:
  - Count of web-triggered analyses, captions, and publishes.
  - Success/failure counts per platform from web-triggered publishes.
- Logs & events:
  - Structured logs for each web action:
    - `web_next_image`, `web_analyze`, `web_caption`, `web_publish`.
  - Include correlation IDs and key parameters (image name, platform list) without secrets.
- Dashboards/alerts:
  - TODO: basic Heroku or external monitoring dashboards to be defined later (e.g., alert on sustained 5xx from the web endpoint).

## Risks & Mitigations
- Risk: Web UI may accidentally allow unintended publishing if protections are too weak.  
  Mitigation: Require an explicit "publish" action only on the currently shown image, add a simple auth/secret, and preserve dry/preview modes as configurable safe defaults.
- Risk: Introducing the web layer could accidentally diverge from CLI behavior.  
  Mitigation: Ensure the web code paths call into `WorkflowOrchestrator` and existing services rather than re-implementing logic; add tests that exercise both CLI and web triggers.
- Risk: Heroku dyno restarts or config drift may break the app.  
  Mitigation: Centralize configuration in environment variables + INI, document deployment steps, and add health-check endpoint.
- Risk: Latency on mobile networks may make actions feel slow.  
  Mitigation: Keep UI simple, provide clear loading indicators and status messages; rely on existing retry and rate-limit logic.

## Open Questions
- What minimal auth mechanism should protect the web UI's analysis/publish actions (basic auth, token in header, simple login form)? — Proposed answer: Start with basic auth or a single shared token configured via env.
- Should anonymous users be able to see any image at all, or should the entire UI require authentication in MVP? — Proposed answer: MVP may restrict entire UI to the operator; public gallery is a later feature.
- How exactly should "preview" vs. "live publish" modes be configured in the web context (separate endpoints, toggle in UI, or config-only)? — Proposed answer: Respect a config flag/environment variable for default mode; optionally add an explicit toggle later.
- Where should the config INI live and how should the web app select it on Heroku? — Proposed answer: Path provided via environment variable; documented in deployment instructions.

## Milestones
- M1: Design & wiring  
  - Exit criteria: Chosen web framework; high-level API design for web endpoints; plan for auth and configuration documented.
- M2: Implementation  
  - Exit criteria: Web server integrated; endpoints for next image, analyze/caption, and publish implemented; sidecar writing and archiving confirmed to behave identically to CLI flows.
- M3: Validation & deployment  
  - Exit criteria: Automated tests for web endpoints; manual end-to-end tests from a phone; Heroku deployment configured and documented; basic logging confirmed in production-like environment.

## Definition of Done
- All acceptance criteria are implemented and verified with automated and/or manual tests.
- Existing CLI workflows remain fully functional and backward compatible.
- Web endpoints are covered by tests for success and failure paths (Dropbox errors, AI errors, publishing errors).
- Documentation updated under `docs_v2/08_Epics` and, where appropriate, overview/architecture docs to mention the web interface.
- A Heroku deployment recipe (including `Procfile`, env vars, and config usage) is documented and verified.
- Structured logs for web-triggered operations are visible and useful for debugging and monitoring.
- No secrets are exposed in logs or UI; basic auth/protection is in place for admin actions.

## Appendix: Source Synopsis
- Discussion about next steps after achieving a working CLI-based MVP, focusing on making the system more accessible and extensible.
- Exploration of various architectural options (enhanced monolith, microservices, event-driven), with a decision to start with a simple web interface rather than a full service split.
- Clarification that streams, multiple storage providers, and MongoDB-based metadata are desired future capabilities but out of scope for this initial web MVP.
- Agreement to reuse Dropbox as the source of truth and sidecar `.txt` files for metadata, avoiding additional data stores.
- Desire to deploy the solution on Heroku and operate it primarily from a mobile browser, with minimal but sufficient safeguards for publishing actions.

