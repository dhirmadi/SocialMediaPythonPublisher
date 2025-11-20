<!-- docs_v2/08_Features/08_04_ChangeRequests/005/005_web-performance-telemetry.md -->

# Web Performance Telemetry — Change Request

**Feature ID:** 005  
**Change ID:** 005-005  
**Name:** web-performance-telemetry  
**Status:** Proposed  
**Date:** 2025-11-20  
**Author:** Architecture Team  
**Parent Feature Design:** docs_v2/08_Features/08_02_Feature_Design/005_web-interface-mvp_design.md  

## Summary
This change adds explicit performance telemetry requirements to the Web Interface MVP, focusing on per-endpoint timing and correlation-friendly logging.  
It defines structured timing fields for key web API calls and clarifies how they should be emitted via the existing logging utilities.  
The goal is to make it easy to measure and enforce latency targets for `/api/images/random`, `/api/images/{filename}/analyze`, and `/api/images/{filename}/publish`.

## Problem Statement
While the web feature defines high-level performance NFRs, it does not currently specify what timing data must be logged or how to correlate slow requests with specific endpoints and backend operations.  
Without consistent performance telemetry, operators and developers cannot reliably diagnose latency issues or validate that NFRs are being met in production.  
Ad-hoc logging risks inconsistency and gaps across endpoints.

## Goals
- Introduce standardized timing fields for all major web endpoints, emitted through `log_json`.  
- Ensure every web request can be correlated with underlying operations (Dropbox, OpenAI, publishing) via correlation IDs and structured logs.  
- Keep the telemetry implementation simple and low-overhead while providing enough data to drive performance improvements.

## Non-Goals
- Adding a full metrics backend or external monitoring tool integration in this change.  
- Changing existing API request/response schemas visible to clients.  
- Modifying business logic or side-effect behavior of the endpoints.

## Affected Feature & Context
- **Parent Feature:** Web Interface MVP  
- **Relevant Sections:**  
  - §3. Requirements – NFR1 Performance and NFR3 Observability.  
  - §4. Architecture & Design – logging expectations for `WebImageService` and FastAPI handlers.  
  - §6. Rollout & Ops – monitoring and logging guidelines.  
- This change refines the observability portion of the web feature by adding precise, testable requirements for what timing data must be logged for each key endpoint.  
- It applies the cross-cutting telemetry pattern defined in `docs_v2/08_Features/08_01_Feature_Request/007_cross-cutting-performance-observability.md` to the web layer.

## User Stories
- As an operator, I want to see how long each web endpoint takes in structured logs, so that I can determine where latency is being spent.  
- As a maintainer, I want consistent performance telemetry across `/random`, `/analyze`, and `/publish`, so that I can benchmark and compare changes over time.  
- As a developer, I want a simple pattern for logging timings around web requests, so that I can instrument new endpoints without reinventing the approach.

## Acceptance Criteria (BDD-style)
- Given a successful call to `/api/images/random`, when the request completes, then the logs must include a timing field (e.g., `web_random_image_ms`) and a correlation ID that can be tied back to the request.  
- Given a call to `/api/images/{filename}/analyze` or `/api/images/{filename}/publish`, when the request completes (success or handled failure), then the logs must include endpoint-specific timing fields (e.g., `web_analyze_ms`, `web_publish_ms`) and any available sub-timing details where practical.  
- Given normal operation under representative load, when logs are inspected, then timing fields must be present for at least a large majority of calls (no silent paths without timing).  
- Given tests for web endpoints, when they run, then they must assert the presence of timing fields in logged output for at least the happy paths.

## UX / UI Requirements
- No UI changes are required; performance telemetry is strictly back-end and log-facing.  
- Any future surface of timing information in the UI must be minimal and should not be introduced by this change.  
- The web UI must continue to behave identically from the user’s perspective regardless of telemetry.

## Technical Notes & Constraints
- Implement timings in FastAPI handlers and/or `WebImageService` using monotonic clocks, and emit them via `utils.logging.log_json` with consistent field names.  
- Reuse or extend existing correlation ID mechanisms so that logs for a request can be grouped.  
- Ensure that logging stays lightweight and does not introduce significant overhead or blocking behavior.  
- Respect existing security and privacy constraints: do not log secrets or sensitive content as part of telemetry.  
- This change is additive and must not alter existing HTTP request/response contracts; by default, clients should see identical behavior aside from improved logs.

## Risks & Mitigations
- Excessive logging could increase log volume and costs — Mitigation: keep messages compact and avoid duplicating data; consider sampling if volume becomes problematic.  
- Incorrect or inconsistent field names could reduce the value of telemetry — Mitigation: document field names and add tests that assert their presence.  
- Timing measurements could be skewed by clock misuse — Mitigation: use `time.monotonic()` or equivalent for measuring durations.

## Open Questions
- Should per-endpoint telemetry include breakdowns for Dropbox vs. OpenAI time, or only total endpoint time? — Proposed answer: start with total endpoint times; add breakdowns later if needed.  
- Do we need a formal schema or JSON structure for all log events, beyond what exists today? — Proposed answer: TODO; may be defined in a separate logging/observability guideline.  
- Should any of this telemetry be surfaced to external dashboards automatically, or is log-based analysis sufficient initially? — Proposed answer: start with log-based analysis only.


