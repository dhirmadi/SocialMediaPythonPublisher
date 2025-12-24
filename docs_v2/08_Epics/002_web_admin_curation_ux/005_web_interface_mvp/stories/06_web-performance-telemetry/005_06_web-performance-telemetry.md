# Web Performance Telemetry

**Feature ID:** 005  
**Change ID:** 005-005  
**Status:** Shipped  
**Date Completed:** 2025-11-20  
**Code Branch / PR:** TODO  

## Summary
This change adds structured performance telemetry to the Web Interface MVP, focusing on per-endpoint timings and correlation-friendly logging for the main web API calls. It introduces standardized `*_ms` duration fields and correlation IDs in logs for `/api/images/random`, `/api/images/{filename}/analyze`, and `/api/images/{filename}/publish`, without altering any HTTP contracts or business logic.

## Goals
- Provide consistent timing data for key web endpoints via `utils.logging.log_json`.
- Ensure every web request can be correlated with underlying operations using a `correlation_id`.
- Keep the telemetry implementation lightweight and safe while supporting latency analysis and future performance improvements.

## Non-Goals
- Introducing a full metrics backend or external monitoring integration.
- Changing JSON request/response schemas for any web endpoints.
- Modifying the business logic, side effects, or auth behavior of existing flows.

## User Value
Operators and maintainers can now inspect structured logs to understand how long web requests take end-to-end and correlate slow requests with specific images and workflows. This makes it easier to validate performance NFRs, detect regressions, and focus optimization efforts on the right parts of the pipeline, all while keeping the web UI behavior unchanged for end users.

## Technical Overview
- **Scope of the change:** Web Interface MVP endpoints and shared logging utilities; the CLI workflow telemetry is aligned but not user-visible in API contracts.
- **Core flow delta:** Each web request now derives a per-request `correlation_id` and start time, then logs an endpoint-specific event (`web_random_image`, `web_analyze_complete`, `web_publish_complete`, plus `*_error` variants) with integer millisecond timings at completion.
- **Key components touched:**
  - `utils.logging`: added `now_monotonic()` and `elapsed_ms(start)` helpers and reused `log_json` for telemetry events.
  - `web.app`: introduced `RequestTelemetry` and `get_request_telemetry`, updated handlers for `/random`, `/analyze`, and `/publish` to emit timing logs and set `X-Correlation-ID`.
  - `web.service`: allowed `analyze_and_caption` to accept an optional `correlation_id` and reused existing AI/sidecar logic.
  - `core.workflow.WorkflowOrchestrator`: emits `workflow_timing` events with per-stage timings and `correlation_id`, complementing web endpoint telemetry.
- **Flags / config:** No new INI or env flags; telemetry is always on for these endpoints and reuses existing `CONFIG_PATH`/`WEB_DEBUG` behavior.
- **Data/state/sidecars:** No changes; sidecar behavior is unchanged and not included in telemetry payloads.

## Implementation Details
- Added `now_monotonic()` and `elapsed_ms(start)` in `utils.logging` to compute integer millisecond durations using `time.perf_counter()` for stability across threads and system clock adjustments.
- Implemented `RequestTelemetry` and `get_request_telemetry` in `web.app` to:
  - Prefer `X-Request-ID` as the `correlation_id` when present, otherwise generate a UUID4.
  - Capture a per-request monotonic `start_time` and attach the correlation ID to `request.state`.
- Updated FastAPI handlers:
  - `GET /api/images/random` logs `web_random_image` or `web_random_image_error` with `web_random_image_ms` and `correlation_id`, and sets an `X-Correlation-ID` response header.
  - `POST /api/images/{filename}/analyze` logs `web_analyze_complete` or `web_analyze_error` with `web_analyze_ms` and `correlation_id`, mapping “not found” conditions to `404`.
  - `POST /api/images/{filename}/publish` logs `web_publish_complete` or `web_publish_error` with `web_publish_ms`, `any_success`, `archived`, and `correlation_id`.
- Threaded an optional `correlation_id` parameter into `WebImageService.analyze_and_caption` so deeper logs can be correlated with the handler-level telemetry.
- Ensured that telemetry logging does not alter response payloads or status codes; any failures in storage/AI/publishing still map to existing error handling paths.
- Updated NFR documentation to explicitly call out `*_ms` timing fields and `correlation_id` as part of the performance and observability story.

## Testing
- **Unit tests:**
  - Extended `test_orchestrator_debug.py` to assert that `WorkflowOrchestrator.execute` emits a `workflow_timing` log entry containing a `correlation_id` and integer timing fields (e.g., `dropbox_list_images_ms`, `image_selection_ms`, `caption_generation_ms`).
- **Integration / E2E tests:**
  - Added `test_e2e_performance_telemetry.py` to:
    - Verify CLI workflow telemetry (`workflow_timing` with `*_ms` and `correlation_id`).
    - Invoke `GET /api/images/random` via `TestClient(app)` when a real-ish config is available and assert that logs contain `web_random_image*` entries with `correlation_id` and integer `web_random_image_ms`.
  - Existing web service tests (`test_web_service.py`) continue to validate behavior of `WebImageService` without depending on telemetry details.
- **Manual checks (recommended):**
  - On a staging deployment, inspect logs while hitting `/api/images/random`, `/analyze`, and `/publish` to confirm presence of timing fields and correlation IDs, including error scenarios.

## Rollout Notes
- **Feature/change flags:** Telemetry is always enabled for the covered endpoints; there is no dedicated feature flag beyond the existing web enablement.
- **Monitoring / logs:** Operators should monitor `workflow_timing`, `web_random_image*`, `web_analyze_*`, and `web_publish_*` events and may build dashboards/alerts on `*_ms` fields if desired.
- **Backout strategy:** If telemetry ever needs to be disabled, the safest path is to revert the logging changes in `web.app` and `utils.logging` (and, if necessary, the workflow timing block), without touching HTTP contracts or business logic.

## Artifacts
- Change Request: docs_v2/08_Epics/08_04_ChangeRequests/005/005_web-performance-telemetry.md  
- Change Design: docs_v2/08_Epics/08_04_ChangeRequests/005/005_web-performance-telemetry_design.md  
- Change Plan: docs_v2/08_Epics/08_04_ChangeRequests/005/005_web-performance-telemetry_plan.yaml  
- Parent Feature Design: docs_v2/08_Epics/08_02_Feature_Design/005_web-interface-mvp_design.md  
- PR: TODO  

## Final Notes
- The telemetry pattern introduced here (monotonic timers + `correlation_id` + `*_ms` fields) can be reused for future web endpoints and extended as part of the broader cross-cutting observability feature.  
- Sub-timings (e.g., Dropbox vs. OpenAI durations) and richer metrics backends remain future work and should be layered on top of these foundational logs without breaking existing fields or semantics.
