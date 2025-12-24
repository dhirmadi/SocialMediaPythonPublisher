# Cross-Cutting Performance & Observability — Feature Design

## 1. Summary

**Problem:** The system currently has structured logs and partial correlation IDs, but lacks consistent, end-to-end performance telemetry across CLI workflows and web endpoints. This makes it hard to attribute latency to specific stages (Dropbox, AI, sidecars, publishers, web) and to detect regressions against NFRs.  
**Goals:** Introduce a lightweight, standardized performance and observability model that (a) adds timing fields for key stages, (b) uses correlation IDs to tie logs together, and (c) is easy to extend for future features without adding heavy infrastructure.  
**Non-goals:** Stand up a full observability stack (metrics backend, tracing system), change functional behavior or API contracts for users, or replace feature-specific logging already defined in other change requests (e.g., captionfile, web UI).

## 2. Context & Assumptions

**Current state**
- Logging is centralized around `publisher_v2.utils.logging.log_json`, which emits structured JSON logs with redaction for secrets.
- The CLI `WorkflowOrchestrator.execute` already creates a `correlation_id` for each run and includes it in several AI/caption/sidecar log events and in `WorkflowResult`.
- Web components (`publisher_v2.web.app`, `publisher_v2.web.service`) use `log_json` for key events (admin login/logout, random image, analyze, publish, sidecar writes) but do not consistently include correlation IDs or timings.
- Documentation has begun to refer to timing/correlation needs (e.g., performance review, change requests for AI analysis and web telemetry), but there is no single, canonical telemetry pattern.

**Constraints**
- Must remain backward-compatible with existing CLI arguments, web endpoints, request/response schemas, and preview/dry behaviors.
- Telemetry must use existing logging utilities (`log_json`) and standard library timing facilities only (e.g., `time.perf_counter`).
- Overhead must be negligible (microseconds–low milliseconds per stage); no blocking operations in async paths beyond timing arithmetic and logging.
- Supported Python versions: `>=3.9,<4.0`.

**Dependencies**
- `publisher_v2.utils.logging` as the shared logging utility.
- `publisher_v2.core.workflow.WorkflowOrchestrator` as the CLI orchestration hub.
- `publisher_v2.web.app` and `publisher_v2.web.service.WebImageService` as web entrypoints and services.
- AI services (`publisher_v2.services.ai`) and Dropbox storage (`publisher_v2.services.storage.DropboxStorage`) as key latency sources.

**Assumptions & Open Questions**
- Assumption: Operators consume logs via existing log aggregation (e.g., Heroku / platform logs) and can derive metrics from JSON fields; no new metrics backend is assumed.
- Assumption: Adding optional HTTP headers (e.g., `X-Correlation-ID`) is acceptable and considered backward-compatible.
- Open question: Do we need per-publisher or per-platform timing (e.g., `telegram_publish_ms`) in addition to the aggregate `publish_parallel_ms`?  
  - For now, we will only implement aggregate publish timings and leave per-publisher timings as a possible future extension.
- Open question: Should we define a strict log schema/version for performance events?  
  - For now, we will follow the recommended field names and avoid enforcing a global schema version in code.

## 3. Requirements

### Functional Requirements

1. **CLI workflow timings**
   - For each CLI run via `WorkflowOrchestrator.execute`, emit timing fields for the major stages, at minimum:
     - `dropbox_list_images_ms`
     - `image_selection_ms`
     - `vision_analysis_ms`
     - `caption_generation_ms`
     - `sidecar_write_ms` (only when sidecar write is attempted)
     - `publish_parallel_ms` (only when publish is attempted)
     - `archive_ms` (only when archive is attempted)
   - These timings must be associated with a `correlation_id` that is consistent across all logs for that run.

2. **Web endpoint timings**
   - For major web endpoints, emit endpoint-level timings and correlation IDs:
     - `/api/images/random` → `web_random_image_ms`
     - `/api/images/{filename}/analyze` → `web_analyze_ms`
     - `/api/images/{filename}/publish` → `web_publish_ms`
   - Each request should have a `correlation_id` that is:
     - Derived from the incoming `X-Request-ID` header if present, otherwise a new UUID4 string.
     - Included in relevant `log_json` calls within the endpoint handlers (and optionally service logs).

3. **Correlation IDs**
   - Maintain the existing `correlation_id` behavior in `WorkflowOrchestrator.execute` and ensure it is present in:
     - Workflow-level summary timing log(s).
     - Existing AI/caption/sidecar logs (already partially implemented).
   - Introduce correlation IDs for web requests and, where practical, pass them to underlying services so nested logs can be correlated.

4. **Structured log fields**
   - Timing fields must use the glossary from the feature request:
     - All durations in integer milliseconds, field names suffixed with `_ms`.
     - `correlation_id` field for correlation.
   - Logs must remain valid JSON objects emitted via `log_json`, without leaking secrets, PII, or sensitive content.

5. **Documentation & examples**
   - Update relevant docs to:
     - Describe the new telemetry fields and where they appear.
     - Provide example log snippets showing CLI and web timings with `correlation_id`.

6. **Tests**
   - Add tests to ensure:
     - Presence and basic correctness/shape of timing fields in structured logs for representative workflows and web requests.
     - Correlation IDs are propagated for CLI and web paths as specified.

### Non-Functional Requirements

- **Performance:** Instrumentation overhead must be negligible; timing collection must use monotonic clocks (`time.perf_counter`) and simple arithmetic.
- **Scalability:** Telemetry must work without change as workflow complexity grows, and without relying on external tracing systems.
- **Cost:** No additional paid infrastructure is introduced.
- **Observability:** Logs must be structured and consistent so that downstream tools can derive latency distributions and counts from them.
- **Security & Privacy:** No secrets, PII, or sensitive image details are logged as part of telemetry fields. Correlation IDs are opaque identifiers not derived from user data.
- **Compatibility:** No breaking changes to CLI flags, web endpoints, HTTP status codes, or JSON response schemas.

## 4. Architecture & Design

### Proposed Architecture (diagram description)

- **CLI path**
  - `publisher_v2.app` → `WorkflowOrchestrator.execute(...)`  
  - Within `execute`, we introduce timing capture around major stages (Dropbox image listing, selection, analysis, captioning, sidecar writes, parallel publishing, archive).
  - A final summary log entry (e.g., `"workflow_timing"`) will include the standardized timing fields and `correlation_id`.

- **Web path**
  - `FastAPI` routes in `publisher_v2.web.app` handle HTTP requests.
  - Each relevant handler derives a `correlation_id` and measures total endpoint duration.
  - Endpoint logs use `log_json` to emit `{..., correlation_id, web_*_ms}` fields on success and error.
  - Optionally, the same `correlation_id` is passed into `WebImageService` methods for nested logs.

### Components & Responsibilities

- **`publisher_v2.utils.logging`**
  - Continue to provide `log_json` and `setup_logging`.
  - Optionally provide small helper utilities for timing (e.g., `now_monotonic()` and `elapsed_ms(start)`), using `time.perf_counter`, to standardize timing logic and improve readability.

- **`publisher_v2.core.workflow.WorkflowOrchestrator`**
  - Owns the lifecycle of a CLI workflow and remains the orchestrator for selection → analysis → caption → sidecar → publish → archive.
  - Responsible for:
    - Generating a `correlation_id` (already implemented).
    - Capturing per-stage timings around existing operations.
    - Emitting a summary timing log with the standardized telemetry fields.

- **`publisher_v2.web.app`**
  - FastAPI application and HTTP routes.
  - Responsible for:
    - Deriving a `correlation_id` per incoming request.
    - Measuring total endpoint duration for the key endpoints.
    - Emitting logs including `{correlation_id, web_*_ms}`.
    - Optionally setting an `X-Correlation-ID` response header for operator debugging (additive behavior).

- **`publisher_v2.web.service.WebImageService`**
  - Thin orchestration for web-specific flows.
  - May accept an optional `correlation_id` parameter in its public methods to include in nested logs (`web_vision_analysis_start`, sidecar logs, publish delegation).
  - This parameter will be optional with a default of `None` to avoid breaking existing call sites.

### Data Model / Schemas (before/after)

- **Before**
  - No persisted data model for telemetry.
  - `WorkflowResult` already includes an optional `correlation_id` field used by CLI.
  - Logs include various fields but with ad-hoc timing and no standardized `_ms` names.

- **After**
  - Still no new persisted data models.
  - Logs extended with:
    - `correlation_id` for CLI and web flows.
    - Timing fields (integer milliseconds) using the standardized names:
      - CLI: `dropbox_list_images_ms`, `image_selection_ms`, `vision_analysis_ms`, `caption_generation_ms`, `sidecar_write_ms`, `publish_parallel_ms`, `archive_ms`.
      - Web: `web_random_image_ms`, `web_analyze_ms`, `web_publish_ms`.
  - Any new log entries will continue to follow existing `log_json` structure.

### API / Contracts (request/response; versioning)

- **CLI & Config**
  - No changes to CLI flags, config schema, or environment variables.

- **Web APIs**
  - No changes to request bodies, response bodies, or URL paths.
  - Optional new HTTP response header `X-Correlation-ID` may be added to key endpoints to aid debugging; this is backward-compatible and not required for clients.

### Error Handling & Retries

- Telemetry collection must not change functional error handling:
  - Errors should still be raised or handled as they are today.
  - Timing fields should be best-effort; if timing capture fails for any reason (e.g., unexpected exception near a timer), request/workflow must still progress using existing error semantics.
- Existing retry behavior for external calls (e.g., OpenAI, Dropbox) remains unchanged; telemetry will measure the time including such retries.

### Security, Privacy, Compliance

- Only non-sensitive identifiers and durations are logged:
  - `correlation_id`: opaque UUID4 or derived from a header intended for correlation (not user PII).
  - Timing fields: numeric durations in milliseconds.
- No secrets, tokens, or raw passwords are included in telemetry fields; redaction in `sanitize` still applies to the `message` field and any text values.
- Telemetry respects existing security guidance in `docs_v2/04_Security_Privacy/SECURITY_PRIVACY.md`.

## 5. Detailed Flow

### CLI Workflow (Orchestrator)

1. **Start workflow**
   - `WorkflowOrchestrator.execute` generates `correlation_id` (existing behavior).
2. **Dropbox list & selection**
   - Capture `t0 = now_monotonic()` before `list_images`.
   - After listing and dedup-selection logic completes:
     - `dropbox_list_images_ms` = time spent in `list_images`.
     - `image_selection_ms` = additional time spent scanning/hashing to pick an image.
   - If no images / no new images, still emit a summary timing log with whatever partial timings are known.
3. **Vision analysis**
   - Capture `t = now_monotonic()` before `analyzer.analyze`.
   - On completion, compute `vision_analysis_ms`.
   - Include `correlation_id` and timing in either a dedicated timing log or the existing `vision_analysis_complete` log.
4. **Caption generation**
   - Capture `t = now_monotonic()` before caption/SD caption branch.
   - On completion/fallback, compute `caption_generation_ms`.
   - Add timing field to a log event associated with caption completion.
5. **Sidecar write (if applicable)**
   - Around the sidecar-writing block (including metadata build and Dropbox write):
     - Capture `t = now_monotonic()` and compute `sidecar_write_ms` upon completion (or failure).
   - Include `sidecar_write_ms` and `correlation_id` in `sidecar_upload_complete` / `sidecar_upload_error` logs and/or final summary.
6. **Parallel publish (if applicable)**
   - Around `asyncio.gather` for publishers:
     - Capture `t = now_monotonic()` before, compute `publish_parallel_ms` after results are processed.
   - Emit timing either in a new `"publish_complete"` summary log or as part of the final workflow timing log.
7. **Archive (if applicable)**
   - Capture `t = now_monotonic()` around the archive operation.
   - Compute `archive_ms` and include it in the final summary log.
8. **Final summary log**
   - At the end of `execute` (before returning `WorkflowResult`), emit a single summary event via `log_json` that includes:
     - `message`: e.g., `"workflow_timing"`.
     - `correlation_id`, `image_name`, `success`, `archived`.
     - All timing fields that were measured for this run.

### Web Endpoints

1. **Random image (`/api/images/random`)**
   - On request entry:
     - Derive `correlation_id` from `X-Request-ID` header or create a new UUID4.
     - Record `t0 = now_monotonic()`.
   - Call `WebImageService.get_random_image`.
   - On success or error:
     - Compute `web_random_image_ms`.
     - Emit `log_json` with:
       - `message`: `"web_random_image"` or `"web_random_image_error"`.
       - `filename` (if available), `correlation_id`, `web_random_image_ms`.
   - Optionally attach `X-Correlation-ID` to the HTTP response.

2. **Analyze (`/api/images/{filename}/analyze`)**
   - Similar pattern:
     - Derive `correlation_id`, record `t0`.
     - Call `WebImageService.analyze_and_caption`.
     - On success or error: compute `web_analyze_ms` and log via `log_json` including `filename`, `correlation_id`, `web_analyze_ms`.
   - Service-level logs (`web_vision_analysis_start`, sidecar logs) may also receive `correlation_id` via an optional parameter.

3. **Publish (`/api/images/{filename}/publish`)**
   - Derive `correlation_id`, record `t0`.
   - Call `WebImageService.publish_image` (which delegates to `WorkflowOrchestrator.execute`).
   - On success or error: compute `web_publish_ms` and log via `log_json` including `filename`, `correlation_id`, `web_publish_ms`, `any_success`, `archived`.

### Edge Cases

- Missing images / no new images:
  - CLI: still log timings for listing and selection; other timings may be omitted.
  - Web: for 404 cases, log timings up to the error point with `*_ms` fields.
- Exceptions in AI or storage:
  - Timings reflect the duration up to the exception.
  - Error logs include `correlation_id` and timing fields where available.
- Preview / dry / debug modes:
  - Telemetry must not cause side effects; timers may still run but sidecar/publish/archive timings may be zero or omitted if those stages are skipped.

## 6. Rollout & Ops

- **Feature flags / Config**
  - No new user-facing config flags are required; telemetry is always-on and low overhead.
  - If needed later, a debug flag could toggle verbosity, but this is out of scope for this feature.

- **Migration / Backfill**
  - No data migrations or backfills; this is log-only.

- **Monitoring, Logging, Dashboards, Alerts**
  - Operators can derive metrics from logs by:
    - Parsing `*_ms` fields for stage/endpoint latency distributions.
    - Using `correlation_id` to stitch related events.
  - Future work may include adding simple scripts or documentation snippets for log analysis; this feature will prepare the telemetry fields for that.

- **Capacity / Cost Estimates**
  - Additional log volume is limited to new fields on existing events plus one summary log per workflow run.
  - CPU overhead for timing is negligible; no new external dependencies.

## 7. Testing Strategy

- **Unit Tests**
  - For `WorkflowOrchestrator`:
    - Use fakes/mocks around storage/AI/publishers to simulate a successful run and assert that:
      - A summary log event is emitted with all expected `*_ms` fields and `correlation_id`.
      - Timing fields are non-negative integers.
  - For web endpoints:
    - Use FastAPI test client to hit `/api/images/random`, `/api/images/{filename}/analyze`, and `/api/images/{filename}/publish` and assert:
      - Logs contain `correlation_id` and appropriate `web_*_ms` fields.
      - `X-Correlation-ID` is present if implemented.

- **Integration / E2E Tests**
  - Existing E2E workflows (e.g., single image through CLI, web analyze + publish) extended to:
    - Validate presence and basic shape of telemetry fields in captured logs.
    - Confirm that the same `correlation_id` is used across related events.

- **Performance Tests**
  - Re-run representative test suites and/or manual workflows to confirm no material regression in latency attributable to telemetry.

## 8. Risks & Alternatives

**Risks**
- **Log noise:** Over-instrumentation could make logs harder to read.
  - *Mitigation:* Limit to high-value timing fields and a single summary event per workflow; avoid duplicating timings across multiple events unless clearly useful.
- **Inconsistent adoption:** Future features might not follow the same patterns.
  - *Mitigation:* Centralize naming and patterns in this design and glossary; enforce via tests and documentation.
- **Accidental leakage of sensitive data in telemetry:**
  - *Mitigation:* Restrict telemetry fields to identifiers and durations; reuse `sanitize` and avoid logging raw content or secrets.

**Alternatives Considered**
- Full distributed tracing solution (e.g., OpenTelemetry):
  - Rejected as overkill for current scope and out of alignment with project constraints.
- Per-publisher detailed timings:
  - Deferred to future work; current design focuses on aggregate `publish_parallel_ms`.

## 9. Work Plan

- **Milestones**
  - M1: Implement CLI workflow summary timings and correlation ID usage in `WorkflowOrchestrator`.
  - M2: Implement web endpoint timings and correlation IDs in `publisher_v2.web.app` (and optional propagation to `WebImageService`).
  - M3: Add tests for telemetry presence and basic correctness; update docs with examples.

- **Definition of Done**
  - CLI and web logs include the standardized timing fields and `correlation_id` as described.
  - Tests cover the new telemetry behavior and remain green.
  - Documentation describes how operators can interpret the new fields.
  - No regressions in functional behavior or performance attributable to telemetry.

## 10. Appendices

- **Glossary**
  - `correlation_id`: String tying together all logs for a single workflow run or web request.
  - `*_ms`: Integer millisecond duration fields for specific stages or endpoints.

- **References**
  - `docs_v2/08_Epics/08_01_Feature_Request/007_cross-cutting-performance-observability.md`
  - `docs_v2/06_NFRs/NFRS.md`
  - Performance review: `docs_v2/09_Reviews/PERFORMANCE_REVIEW_2025-11.md`


