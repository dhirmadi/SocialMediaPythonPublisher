<!-- docs_v2/08_Epics/08_04_ChangeRequests/005/005_web-performance-telemetry_design.md -->

# Web Performance Telemetry — Change Design

**Feature ID:** 005  
**Change ID:** 005-005  
**Parent Feature:** Web Interface MVP  
**Design Version:** 1.0  
**Date:** 2025-11-20  
**Status:** Design Review  
**Author:** TODO  
**Linked Change Request:** docs_v2/08_Epics/08_04_ChangeRequests/005/005_web-performance-telemetry.md  
**Parent Feature Design:** docs_v2/08_Epics/08_02_Feature_Design/005_web-interface-mvp_design.md  

## 1. Summary

- This change adds explicit, structured performance telemetry for the main web API endpoints of the Web Interface MVP, without altering any HTTP contracts or business logic.
- The focus is on per-request duration fields and correlation IDs emitted via `log_json`, so operators can validate latency NFRs and diagnose slow calls in production.
- The implementation follows the cross-cutting observability pattern from Feature 007 while remaining scoped to the web layer and reusing existing logging utilities.

## 2. Context & Assumptions

- **Current behavior (affected parts only):**
  - FastAPI app in `publisher_v2.web.app` exposes `/api/images/random`, `/api/images/{filename}/analyze`, `/api/images/{filename}/publish`.
  - Requests are logged via `utils.logging.log_json` in an ad-hoc way; there is no guaranteed per-endpoint timing field.
  - The CLI workflow (`WorkflowOrchestrator`) has been updated separately (as part of cross-cutting telemetry work) to emit `workflow_timing` events with `*_ms` fields and a `correlation_id`.
- **Constraints from parent feature:**
  - No changes to request/response JSON schemas for web endpoints.
  - Observability must reuse `log_json` and correlation IDs; logs must avoid secrets and unnecessary payload.
  - Web endpoints have latency NFRs but cannot introduce significant overhead through telemetry.
- **Dependencies:**
  - `publisher_v2.utils.logging.log_json` as the central logging primitive.
  - `publisher_v2.utils.logging.now_monotonic` / `elapsed_ms` for timing based on a monotonic clock.
  - `publisher_v2.web.service.WebImageService` for underlying web flows.
  - `publisher_v2.core.workflow.WorkflowOrchestrator` for publish behavior and its own `workflow_timing` telemetry.

## 3. Requirements

### 3.1 Functional Requirements

- **CR1:** Each successful call to `GET /api/images/random` must emit a structured log entry with a `web_random_image_ms` duration field and a `correlation_id`.
- **CR2:** Each call (success or handled failure) to `POST /api/images/{filename}/analyze` must emit a structured log with `web_analyze_ms` and `correlation_id`.
- **CR3:** Each call (success or handled failure) to `POST /api/images/{filename}/publish` must emit a structured log with `web_publish_ms`, `correlation_id`, and basic outcome flags (e.g., `any_success`, `archived`).
- **CR4:** The telemetry implementation must not modify HTTP response bodies or status codes beyond existing behavior; clients see identical contracts.
- **CR5:** At least one automated test must assert the presence of timing fields and `correlation_id` in web logs for a happy-path request.

### 3.2 Non-Functional Requirements

- Telemetry must add **minimal overhead**: use monotonic timers and simple integer millisecond fields; no blocking I/O beyond the existing endpoint work.
- Logging must remain **security-conscious**: no secrets, captions, or large payloads in timing events; reuse existing sanitization in `log_json`.
- Telemetry must be **consistent and correlation-friendly**:
  - Every web timing event includes a `correlation_id`.
  - Where available, the same ID can be reused downstream (e.g., passed into `WebImageService` and onward to the workflow).
- Implementation should be **backward compatible** and easily extensible to future endpoints.

## 4. Architecture & Design (Delta)

### 4.1 Current vs. Proposed

- **Current:**
  - Web endpoints perform their logic via `WebImageService` and log some events, but per-endpoint timings are not guaranteed or standardized.
  - Correlation IDs are not consistently derived from incoming requests, nor always attached to web logs.
- **Proposed:**
  - Introduce a small request-scoped telemetry helper (correlation ID + monotonic start time) for FastAPI handlers.
  - Use `elapsed_ms` at the end of each handler to compute endpoint-specific `*_ms` fields and emit them via `log_json`, along with `correlation_id`.
  - Leave `WebImageService` behavior unchanged, aside from accepting an optional `correlation_id` for more detailed logging, and rely on existing workflow `workflow_timing` logs for deeper breakdowns.

### 4.2 Components & Responsibilities

- `publisher_v2.utils.logging`  
  - **New responsibilities:** provide `now_monotonic()` and `elapsed_ms(start)` helpers using `time.perf_counter()` for stable duration measurement.
  - **Existing responsibilities preserved:** JSON logging with sanitization via `log_json`.
- `publisher_v2.web.app`  
  - **New:** `RequestTelemetry` dataclass and `get_request_telemetry` dependency to:
    - Derive a `correlation_id` from `X-Request-ID` when present, else generate a UUID4.
    - Capture a monotonic `start_time` for each request.
  - **Updated endpoints:**
    - `/api/images/random`: compute `web_random_image_ms`, emit `web_random_image` / `web_random_image_error` logs, and set `X-Correlation-ID` header.
    - `/api/images/{filename}/analyze`: compute `web_analyze_ms`, emit `web_analyze_complete` / `web_analyze_error` logs, and set `X-Correlation-ID`.
    - `/api/images/{filename}/publish`: compute `web_publish_ms`, emit `web_publish_complete` / `web_publish_error` logs, and set `X-Correlation-ID`.
- `publisher_v2.web.service.WebImageService`  
  - **Minor change:** `analyze_and_caption` accepts an optional `correlation_id` to attach to its own logs; core behavior and return shapes remain unchanged.
- `publisher_v2.core.workflow.WorkflowOrchestrator`  
  - **Contextual (from cross-cutting telemetry):** emits `workflow_timing` events with per-stage `*_ms` fields and `correlation_id`, which can be used in conjunction with web endpoint timings but is not directly changed by this story’s external contracts.

### 4.3 Data & Contracts

- **HTTP contracts (unchanged):**
  - Request/response schemas for `/api/images/random`, `/api/images/{filename}/analyze`, `/api/images/{filename}/publish` remain identical to the parent feature design.
- **Logging contracts (new/clarified):**
  - `web_random_image` and `web_random_image_error` events:
    - Fields: `message`, `filename` (when available), `correlation_id`, `web_random_image_ms`.
  - `web_analyze_complete` and `web_analyze_error` events:
    - Fields: `message`, `filename`, `correlation_id`, `web_analyze_ms`.
  - `web_publish_complete` and `web_publish_error` events:
    - Fields: `message`, `filename`, `any_success` (where applicable), `archived` (where applicable), `correlation_id`, `web_publish_ms`.
  - All timing fields are integer millisecond durations from handler entry to completion.
- **Headers:**
  - `X-Correlation-ID` response header is set for the instrumented endpoints, mirroring the derived correlation ID.

### 4.4 Error Handling & Edge Cases

- Endpoint timings must be logged **even when errors occur**:
  - For `/api/images/random`: on unexpected exceptions, log `web_random_image_error` with `web_random_image_ms` and return `500`.
  - For `/analyze` and `/publish`: on unexpected exceptions, log `web_analyze_error` / `web_publish_error` with timing fields and return `500`; known “not found” conditions map to `404` without leaking internal details.
- If `X-Request-ID` is missing or malformed, a new UUID4 correlation ID is generated; logging continues as normal.
- Telemetry must not throw: any failure inside logging (e.g., serialization) should not break request handling; this is already guaranteed by `log_json` behavior.

### 4.5 Security, Privacy, Compliance

- Do not log:
  - Full captions, sidecar contents, or user-auth data as part of timing events.
  - Secrets (tokens, API keys), which are already sanitized by `log_json.sanitize`.
- Correlation IDs are opaque and non-sensitive.
- Telemetry adheres to existing logging guidelines and does not alter auth, access control, or PII handling.

## 5. Detailed Flow

- **Flow A: `GET /api/images/random`**
  1. `get_request_telemetry` runs, deriving `correlation_id` and `start_time`.
  2. Handler invokes `WebImageService.get_random_image()`.
  3. On success, handler computes `web_random_image_ms = elapsed_ms(start_time)`.
  4. Handler sets `X-Correlation-ID` on the response and emits `web_random_image` log via `log_json`.
  5. On exception, handler computes `web_random_image_ms`, logs `web_random_image_error` with the same `correlation_id`, and returns a `500` error.
- **Flow B: `POST /api/images/{filename}/analyze`**
  1. `get_request_telemetry` runs as above.
  2. Auth and (optional) admin checks are performed.
  3. Handler calls `WebImageService.analyze_and_caption(filename, correlation_id=telemetry.correlation_id)`.
  4. On success, computes `web_analyze_ms`, sets `X-Correlation-ID`, and logs `web_analyze_complete`.
  5. On “not found” errors, maps to `404` without a telemetry change besides timing; other exceptions log `web_analyze_error` with `web_analyze_ms` then return `500`.
- **Flow C: `POST /api/images/{filename}/publish`**
  1. `get_request_telemetry` runs.
  2. Auth and admin checks run.
  3. Handler calls `WebImageService.publish_image(...)`, which delegates to `WorkflowOrchestrator.execute`.
  4. On success, computes `web_publish_ms`, sets `X-Correlation-ID`, and logs `web_publish_complete` including `any_success` and `archived`.
  5. On “not found” errors, returns `404`; other exceptions log `web_publish_error` with `web_publish_ms` and return `500`.

## 6. Testing Strategy (for this Change)

- **Unit / service-level tests:**
  - Ensure that telemetry helpers (`now_monotonic`, `elapsed_ms`) return monotonic, non-negative durations.
  - Validate that `WorkflowOrchestrator.execute` emits a `workflow_timing` log with `correlation_id` and integer `*_ms` fields (covered by orchestrator tests, shared with cross-cutting telemetry Feature 007).
- **Integration / web tests:**
  - Use `TestClient(app)` to invoke `GET /api/images/random` against a configured environment and assert:
    - A `web_random_image*` log entry is emitted.
    - The JSON log contains a `correlation_id` and integer `web_random_image_ms`.
  - Additional tests (optional but recommended) for `/analyze` and `/publish` may follow the same pattern with mocked dependencies.
- **E2E / manual checks:**
  - Deploy to staging and verify that production logs show:
    - Timing fields for a majority of calls to the three endpoints.
    - Correlation IDs that can be used to group web requests and downstream workflow logs.

## 7. Risks & Alternatives

- **Risks:**
  - Increased log volume due to additional telemetry events.
    - *Mitigation:* Keep events compact and avoid duplicating data; future sampling can be added if needed.
  - Inconsistent field naming could reduce observability value.
    - *Mitigation:* Centralize names in this design and enforce via tests.
  - Misuse of non-monotonic clocks could skew timings.
    - *Mitigation:* Use `time.perf_counter()` via `now_monotonic` consistently.
- **Alternatives Considered:**
  - Adding a metrics backend (Prometheus, StatsD) in this change:
    - Rejected as over-scoped; log-based telemetry is sufficient for the MVP.
  - Performing timing exclusively in `WebImageService`:
    - Rejected for per-endpoint clarity; handler-level timings more directly reflect user-perceived latency.
  - Embedding timings in HTTP responses:
    - Rejected to avoid contract changes and potential client coupling.

## 8. Work Plan (Scoped)

- Implement `now_monotonic` and `elapsed_ms` helpers in `publisher_v2.utils.logging` and use them where timing is needed.
- Add `RequestTelemetry` and `get_request_telemetry` in `publisher_v2.web.app` to derive `correlation_id` and record `start_time` per request.
- Update `/api/images/random`, `/api/images/{filename}/analyze`, and `/api/images/{filename}/publish` handlers to:
  - Depend on `RequestTelemetry`,
  - Compute `*_ms` durations via `elapsed_ms`,
  - Emit structured logs with `correlation_id` and timing fields,
  - Set `X-Correlation-ID` on responses.
- Optionally thread `correlation_id` into `WebImageService.analyze_and_caption` and its logs for deeper correlation.
- Add or extend tests to assert the presence of timing fields and correlation IDs in logs (at least for `/api/images/random` and for CLI orchestrator runs).

## 9. Open Questions

- Should web telemetry be extended to include sub-timings (e.g., Dropbox vs. OpenAI) within the same request? — Proposed answer: defer to cross-cutting telemetry Feature 007; start with total endpoint time only.
- Should timing fields be part of a more formalized log schema (e.g., a `telemetry` object)? — Proposed answer: not in this change; keep flat fields and revisit once broader observability guidelines are defined.
- Do we want to expose correlation IDs back to clients beyond the `X-Correlation-ID` header (e.g., in response bodies)? — Proposed answer: no; the header is sufficient for support workflows without changing JSON contracts.


