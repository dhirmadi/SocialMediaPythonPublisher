# Cross-Cutting Performance & Observability

**Feature ID:** 007-cross-cutting-performance-observability  
**Status:** Shipped  
**Date Completed:** 2025-11-20  
**Code Branch / PR:** feature/007-cross-cutting-performance-observability (PR: TODO)  

## Summary
This feature introduces a lightweight, standardized performance telemetry layer across the V2 CLI workflow and web interface, using existing structured logging utilities. It adds stage-level timing fields and correlation IDs so operators can trace and diagnose latency across Dropbox, AI analysis, captioning, sidecar generation, publishing, and web endpoints without changing application behavior.

## Goals
- Provide consistent, structured timings for key workflow stages (selection, analysis, captioning, sidecar write, publish, archive).
- Add correlation IDs so all logs for a single workflow run or web request can be tied together.
- Enable operators to derive performance baselines and detect regressions using logs alone.
- Keep the implementation lightweight, using standard library timing and existing `log_json` utilities.

## Non-Goals
- Introducing a full observability stack (metrics backend, distributed tracing, dashboards).
- Changing CLI flags, web endpoint contracts, or user-visible behavior solely for telemetry.
- Replacing or rewriting feature-specific logging already covered by other change requests.

## User Value
Operators and maintainers can now see where time is spent for each run (e.g., Dropbox listing vs. OpenAI calls vs. publishing) and for each web request, making performance issues significantly easier to diagnose. The standardized fields enable simple log-based analysis and future tooling to monitor SLOs without adding heavy infrastructure or coupling to a particular observability vendor.

## Technical Overview
- **Core flow**
  - CLI workflows via `WorkflowOrchestrator.execute` now measure and log durations for major stages (`dropbox_list_images_ms`, `image_selection_ms`, `vision_analysis_ms`, `caption_generation_ms`, `sidecar_write_ms`, `publish_parallel_ms`, `archive_ms`) alongside a per-run `correlation_id`.
  - Web endpoints (`/api/images/random`, `/api/images/{filename}/analyze`, `/api/images/{filename}/publish`) now derive a per-request `correlation_id`, measure total endpoint latency, and log `web_random_image_ms`, `web_analyze_ms`, and `web_publish_ms` respectively.
- **Key components touched**
  - `utils.logging`: added monotonic timing helpers used across the system.
  - `core.workflow.WorkflowOrchestrator`: extended with per-stage timers and a `workflow_timing` summary log.
  - `web.app`: endpoint handlers now generate correlation IDs and endpoint-level timing telemetry.
  - `web.service.WebImageService`: analysis and sidecar logs now include the web correlation ID when available.
- **Flags / config**
  - No new runtime flags were introduced; telemetry is always-on and designed to be low overhead.
  - Existing environment variables for web configuration (`CONFIG_PATH`, etc.) remain unchanged.
- **Data model updates**
  - No persisted models changed; telemetry fields are log-only.
  - `WorkflowResult` continues to carry `correlation_id` for CLI runs as before.
- **External API usage**
  - External services (Dropbox, OpenAI, publishers) are unchanged; telemetry measures the time spent around existing calls.

## Implementation Details
- Key functions and classes:
  - `utils.logging.now_monotonic()` and `utils.logging.elapsed_ms(start)` use `time.perf_counter` to provide monotonic timestamps and integer millisecond durations.
  - `WorkflowOrchestrator.execute(...)` now:
    - Measures Dropbox listing, image selection, vision analysis, caption generation, sidecar writes, parallel publishing, and archiving.
    - Emits a `workflow_timing` log via `log_json` with `correlation_id` and all measured `*_ms` fields, plus `preview_mode` and `dry_publish` flags for context.
  - `web.app`:
    - Introduces `_get_correlation_id(request)` which uses `X-Request-ID` when present or falls back to a new UUID4.
    - `api_get_random_image`, `api_analyze_image`, and `api_publish_image` now measure total endpoint duration and log `web_*_ms` fields with `correlation_id` on both success and error paths.
  - `web.service.WebImageService.analyze_and_caption` accepts an optional `correlation_id` and includes it on `web_vision_analysis_start` and sidecar-related logs.
- Error handling:
  - Telemetry is best-effort and does not alter existing error flows; exceptions are still handled as before, with timing fields reflecting the duration up to the error.
  - Fallback caption generation logic on SD caption failure is preserved; both success and fallback paths record `caption_generation_ms`.
- Performance and reliability:
  - Timing helpers use monotonic clocks and simple arithmetic, adding negligible overhead.
  - Telemetry is emitted via the existing `log_json` mechanism, keeping log volume modest (primarily by adding fields to existing events and one summary event per workflow run).
- Security and privacy:
  - Logged telemetry fields are limited to opaque identifiers (`correlation_id`) and numeric durations (`*_ms`).
  - No secrets, tokens, or image contents are added; existing `sanitize` behavior continues to protect message content.

## Testing
The testing strategy extends existing coverage and adds targeted checks for telemetry:
- **Unit / integration tests**
  - `test_orchestrator_debug.py` now verifies that `WorkflowOrchestrator.execute` emits a `workflow_timing` log with a `correlation_id` and integer timing fields for listing, selection, and caption generation.
  - `test_web_service.py` continues to validate `WebImageService` behavior with an in-memory config stub, ensuring web-side logic remains correct despite telemetry changes.
- **E2E / feature tests**
  - `test_e2e_performance_telemetry.py` adds:
    - A CLI-focused test confirming that a full workflow run produces `workflow_timing` logs with expected `*_ms` fields.
    - A web-focused test that (when a real `CONFIG_PATH` is available) exercises `/api/images/random` and asserts the presence of `web_random_image_ms` and `correlation_id` in logs, with a skip when config is not present.
- **Regression coverage**
  - The full pytest suite passes, with existing E2E and integration tests (CLI, AI, sidecars, web auth/UI) confirming no behavioral regressions.

## Rollout Notes
- Feature flags:
  - No runtime feature flag is used; telemetry is considered safe and always enabled.
  - The feature plan tracks a logical `features.telemetry_007` flag for release bookkeeping only.
- Monitoring and logs:
  - Operators should filter `workflow_timing` events and `web_*` log messages to surface stage and endpoint latencies.
  - Timing field names follow the glossary from the feature request (`*_ms`) to ease downstream parsing.
- Backout strategy:
  - If required, rollback consists of reverting the minimal telemetry-related changes in `utils.logging`, `core.workflow`, and `web` modules; no migrations or persistent schema changes are involved.

## Artifacts
- Design doc: `docs_v2/08_Features/08_02_Feature_Design/007_cross-cutting-performance-observability_design.md`
- Plan: `docs_v2/08_Features/08_03_Feature_plam/007_cross-cutting-performance-observability_plan.yaml`
- PR: TODO

## Final Notes
This feature establishes a common pattern for performance telemetry that future work (e.g., captionfile, expanded analysis, web performance tuning) can build upon. Potential follow-ups include per-publisher timing fields, lightweight log-analysis helpers for operators, and optional response headers (e.g., `X-Correlation-ID`) to expose correlation IDs directly to API clients. The current implementation keeps overhead low while making performance behavior significantly more observable.***

