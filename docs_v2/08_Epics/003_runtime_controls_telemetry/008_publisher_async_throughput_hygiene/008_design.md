<!-- docs_v2/08_Epics/08_02_Feature_Design/008_publisher-async-throughput-hygiene_design.md -->

## Publisher Async Throughput Hygiene — Feature Design (ID: 008)

### Assumptions & Open Questions

- **Assumption A1**: Telegram and Instagram SDK versions in use support the current async usage patterns (`await bot.send_photo`, `instagrapi.Client` in a thread) and we will not change SDK versions in this feature.
- **Assumption A2**: The primary async bottlenecks in the publish phase are (a) image resizing via `utils.images.ensure_max_width` and (b) blocking third‑party SDKs (SMTP, Instagrapi); Dropbox and AI services are already handled via async clients and existing rate‑limiters.
- **Assumption A3**: We can rely on the existing `WorkflowOrchestrator` timing telemetry (`publish_parallel_ms`) as the authoritative measure for overall publish phase duration, and we will extend (but not replace) it with per‑publisher timings.
- **Open Question Q1**: Do we want long‑term “micro‑benchmark” style tests/benchmarks in a separate performance test suite (outside `pytest -v`), or is a lightweight concurrency test in the main suite sufficient for now?
- **Open Question Q2**: Should we introduce explicit per‑publisher timeout configuration in this feature, or continue to rely on existing SDK timeouts and tenacity usage elsewhere?

---

## 1. Summary

**Problem**  
Publishers are invoked in parallel via `asyncio.gather`, but some publisher implementations still perform blocking work (notably image resizing with Pillow and non‑async SDKs) directly in the event loop. This risks stalling the loop and eroding the intended concurrency gains in the publish phase.

**Goals**
- Ensure all publishers are “async‑safe”: heavy CPU or blocking I/O is offloaded from the event loop, while async SDK calls remain awaited directly.
- Standardize a small set of implementation patterns for async publishers (wrapping blocking work with `asyncio.to_thread`, structured timing logs, clear error propagation).
- Add tests and minimal telemetry to validate that multi‑platform publishing is effectively concurrent and that enabling additional publishers has modest latency impact.

**Non‑Goals**
- No new publisher platforms, business rules, or queueing/scheduling systems.
- No changes to preview/dry‑run semantics, sidecar behavior, or AI workflows.
- No schema or external API contract changes; this is primarily an internal hygiene and observability improvement.

---

## 2. Context & Assumptions

### Current State

- **Orchestration**
  - `WorkflowOrchestrator.execute` (`core.workflow`) runs the end‑to‑end flow and publishes via:
    - `enabled_publishers = [p for p in self.publishers if p.is_enabled()]`
    - `results = await asyncio.gather(*(p.publish(...)), return_exceptions=True)`
    - Overall publish timing is tracked as `publish_parallel_ms` in the `workflow_timing` JSON log.
- **Publishers**
  - `EmailPublisher` (`services.publishers.email`):
    - Uses `smtplib.SMTP` and `email.mime` to construct and send messages.
    - All SMTP connection and send operations are wrapped in `await asyncio.to_thread(_send_emails)`, so heavy work is already offloaded.
  - `TelegramPublisher` (`services.publishers.telegram`):
    - Synchronously calls `ensure_max_width(image_path, max_width=1280)` from `utils.images`.
    - Uses an async `telegram.Bot` client: `await bot.send_photo(...)`, followed by `await bot.shutdown()`.
    - Image resizing is CPU+I/O bound and currently runs on the event loop thread.
  - `InstagramPublisher` (`services.publishers.instagram`):
    - Synchronously calls `ensure_max_width(image_path, max_width=1080)` before dispatching blocking Instagrapi calls.
    - Wraps the Instagrapi client work (`login`, `photo_upload`, etc.) in `await asyncio.to_thread(_upload)`.
    - Resizing work still runs on the event loop.
- **Image Utilities**
  - `utils.images.ensure_max_width`:
    - Uses Pillow (`PIL.Image`) to open, potentially resize, and save images synchronously to disk.
    - Called directly from publishers in async contexts, making it a likely event‑loop bottleneck.
- **Telemetry & Observability**
  - `workflow_timing` logs include `publish_parallel_ms` but not per‑publisher timings.
  - Cross‑cutting performance docs already highlight `ensure_max_width` as a synchronous risk.

### Constraints & Dependencies

- Architecture must remain **async‑first**: no new blocking layers inside orchestrator or web handlers.
- Preview and dry‑run modes must remain **side‑effect free** (no external platform calls, no archival or state mutation).
- No new persistent queues, brokers, or scheduler frameworks; reuse existing retry and error‑handling patterns.
- Respect security/privacy rules: no logging of secrets; all logs must use the structured `log_json` helper.

---

## 3. Requirements

### Functional Requirements

1. **FR1 – Async‑Safe Image Resizing**
   - When Telegram or Instagram publishers resize images, the resizing must not block the event loop; resizing must be performed via a non‑blocking pattern (e.g., `asyncio.to_thread` around `ensure_max_width`).
2. **FR2 – Async‑Safe Publisher SDK Usage**
   - Any publisher operations using blocking SDKs (SMTP, Instagrapi, etc.) must be encapsulated in `asyncio.to_thread` or equivalent, so that no blocking SDK calls run directly on the event loop.
3. **FR3 – Preserve Behavior**
   - Publisher outputs (messages, captions, attachments, side effects such as archives) must remain identical to current behavior, aside from timing and additional observability.
4. **FR4 – Per‑Publisher Timing Telemetry**
   - For each publisher invocation in a non‑preview, non‑debug, non‑dry run, record a structured log entry with at least: `platform`, `duration_ms`, `success`, and an optional `error` field.
5. **FR5 – Concurrency Validation Tests**
   - Add tests that exercise `WorkflowOrchestrator` with multiple dummy publishers and verify that their publish operations run concurrently (i.e., parallel overlap in timing, not serialized).
6. **FR6 – Async Hygiene Documentation**
   - Document the async publisher patterns (when to use `asyncio.to_thread`, how to structure blocking work, how to log timings) in `docs_v2/08_Epics` and/or existing NFR/architecture docs.
7. **FR7 – Preview/Dry‑Run Compatibility**
   - Ensure preview and dry‑run flows remain functionally unchanged; tests must continue to pass and no new side effects are introduced under these modes.

### Non‑Functional Requirements

1. **NFR1 – Performance**
   - Multi‑platform publish latency should approximate the latency of the slowest publisher, not the sum of all publishers, under healthy external services.
   - Additional overhead from `asyncio.to_thread` and timing logs should be negligible compared to network I/O.
2. **NFR2 – Scalability**
   - The design should continue to work correctly as new publishers are added, reusing the same patterns without spawning unbounded threads or blocking the event loop.
3. **NFR3 – Reliability & Error Handling**
   - Exceptions from publisher operations must be surfaced back to `WorkflowOrchestrator` as `PublishResult` entries, preserving existing semantics for mixed‑success cases.
4. **NFR4 – Observability**
   - Per‑publisher telemetry should be captured in structured logs suitable for downstream dashboards and alerts, consistent with existing logging conventions.
5. **NFR5 – Security & Privacy**
   - No secrets (tokens, passwords) may be logged in new telemetry; only platform names and high‑level status may be included.

---

## 4. Architecture & Design

### 4.1 Proposed Architecture (High‑Level)

- **Current**: `WorkflowOrchestrator.execute` selects images, invokes AI, generates captions, writes sidecars, then publishes in parallel via `asyncio.gather`. Publishers individually manage their own SDK calls and any preprocessing like image resizing.
- **Proposed**:
  - Keep orchestration unchanged: `WorkflowOrchestrator` remains the single orchestrator calling `publish` on each `Publisher`.
  - Introduce an **async wrapper** around image resizing (`ensure_max_width_async`) that internally delegates to the existing synchronous `ensure_max_width` via `asyncio.to_thread`.
  - Refactor Telegram and Instagram publishers to:
    - Use `ensure_max_width_async` inside their `publish` methods.
    - Wrap blocking SDK sequences in small inner functions executed via `asyncio.to_thread` (Instagram already does this; no change needed there).
    - Emit per‑publisher timing logs using `log_json` with a consistent schema.
  - Add tests at the workflow level that construct dummy publishers to validate:
    - True concurrency of publishes (time intervals overlap).
    - Non‑regression of behavior in preview/dry‑run modes.

### 4.2 Components & Responsibilities

- **`WorkflowOrchestrator` (`core.workflow`)**
  - Continues to orchestrate the workflow and aggregate `PublishResult`s.
  - Remains responsible for `publish_parallel_ms` but not for per‑publisher timing internals.

- **`Publisher` interface (`services.publishers.base`)**
  - Unchanged interface: `platform_name`, `is_enabled`, `async publish(...) -> PublishResult`.
  - Implicit contract: `publish` must not perform long‑running blocking operations directly on the event loop.

- **Publishers (`services.publishers.email`, `telegram`, `instagram`)**
  - **EmailPublisher**:
    - Already uses `asyncio.to_thread(_send_emails)`; will only gain optional per‑publisher timing logs.
  - **TelegramPublisher**:
    - Move image resizing to `ensure_max_width_async` (offload via `asyncio.to_thread`).
    - Maintain async `bot.send_photo` usage.
    - Add per‑publisher timing logs.
  - **InstagramPublisher**:
    - Move image resizing to `ensure_max_width_async`.
    - Preserve existing `asyncio.to_thread(_upload)` pattern for Instagrapi client work.
    - Add per‑publisher timing logs.

- **Image Utilities (`utils.images`)**
  - Add an async helper that wraps `ensure_max_width` with `asyncio.to_thread` to create a reusable pattern for other publishers or future code paths.

- **Tests (`publisher_v2/tests`)**
  - New tests will be added under a dedicated file (e.g., `test_publisher_async_throughput.py`) to validate concurrency characteristics and async safety at a unit/integration level.

### 4.3 Data Model / Schemas (Before/After)

- **Before**
  - No dedicated data model for publisher telemetry beyond the aggregated `publish_results` map and `publish_parallel_ms` in `workflow_timing` logs.

- **After**
  - No persisted schema changes.
  - New structured logs of the form (example):
    - `{"event": "publisher_publish", "platform": "telegram", "duration_ms": 123, "success": true, "error": null, "correlation_id": "..."}`
  - These logs are **non‑breaking** and additive; consumers not aware of them can ignore them.

### 4.4 API / Contracts

- **Publisher Interface**
  - Signature remains:
    - `async def publish(self, image_path: str, caption: str, context: Optional[dict] = None) -> PublishResult:`
  - Behavior:
    - Must not block the event loop with synchronous heavy work (by convention and documentation).
    - Must return `PublishResult` or propagate exceptions that `WorkflowOrchestrator` converts into `PublishResult` with `success=False`.

- **WorkflowOrchestrator**
  - Public API unchanged.
  - Logs still emit `workflow_timing` with `publish_parallel_ms`; now, this value should better approximate true parallel publish time even in the presence of resizing and blocking SDKs.

### 4.5 Error Handling & Retries

- **Error Propagation**
  - Inside each publisher, exceptions from blocking inner functions executed via `asyncio.to_thread` must be caught and mapped to `PublishResult(success=False, error=str(exc))`, consistent with existing patterns.
  - `asyncio.gather(..., return_exceptions=True)` remains in use in the orchestrator; any uncaught exceptions are converted to `PublishResult(success=False, error=str(exc))` as today.

- **Retries**
  - No new retry mechanisms are introduced for publisher SDKs in this feature; existing behavior (including any SDK‑internal retries) remains unchanged.
  - Any future retry changes will be handled in a separate feature/CR.

### 4.6 Security, Privacy, Compliance

- New logs must:
  - Exclude sensitive identifiers (e.g., email addresses, tokens, passwords).
  - Include only: platform name, timings, boolean success, and high‑level error message (sanitized via `str(exc)`).
- No new network endpoints, data stores, or external APIs are introduced.

---

## 5. Detailed Flow

### 5.1 Publish Flow with Async‑Safe Publishers

1. **Image Selection, AI, Captioning, Sidecars**
   - Unchanged; orchestrator behavior stays as currently implemented.
2. **Publisher Parallel Execution**
   - Orchestrator builds `enabled_publishers` and invokes `asyncio.gather` over `p.publish(...)` for each publisher.
3. **Within EmailPublisher.publish**
   - Validate enabled/configured.
   - Build `_send_emails` closure with SMTP connect, login, send, and optional confirmation.
   - Record `start = now_monotonic()` in the event loop.
   - `await asyncio.to_thread(_send_emails)` to run blocking SMTP operations in a thread pool.
   - Record `duration_ms` and emit a structured `publisher_publish` log via `log_json`.
   - Return `PublishResult(success=True, platform="email")` or, in case of error, map exception to `PublishResult(success=False, error=...)`.
4. **Within TelegramPublisher.publish**
   - Validate enabled/configured.
   - `processed_path = await ensure_max_width_async(image_path, max_width=1280)`.
   - Record `start = now_monotonic()`.
   - Use async `bot.send_photo` to send the resized image and caption.
   - Record `duration_ms`, log via `log_json` (`publisher_publish`) with success/error, and return `PublishResult` as before.
   - Ensure `await bot.shutdown()` is called in a `finally` block, unchanged.
5. **Within InstagramPublisher.publish**
   - Validate enabled/configured.
   - `processed_path = await ensure_max_width_async(image_path, max_width=1080)`.
   - Record `start = now_monotonic()`.
   - `post_id = await asyncio.to_thread(_upload)` where `_upload` encapsulates Instagrapi usage.
   - Record `duration_ms`, log via `log_json` (`publisher_publish`), and return existing `PublishResult` with `post_id` where available.
6. **Result Aggregation**
   - Orchestrator aggregates per‑publisher `PublishResult`s into its `publish_results` map, unchanged.
   - `publish_parallel_ms` reflects total elapsed time of the parallel publish set.

### 5.2 Edge Cases

- **No Enabled Publishers**
  - Orchestrator currently simulates success in debug mode and skips real publish calls when no publishers are enabled or when in preview/dry‑run; this behavior remains unchanged.
- **Preview/Dry‑Run Modes**
  - Orchestrator never calls real `publish` methods in these modes; publisher changes are therefore inert for preview/dry‑run, satisfying the “no side effects” requirement.
- **Partial Failures**
  - Some publishers may succeed while others fail. Existing behavior (archiving only when any_success and not debug/dry/preview) remains unchanged.
- **Thread Pool Exhaustion**
  - The use of `asyncio.to_thread` defers to the event loop’s default executor. Empirically, the number of concurrent publisher calls is small (1–3), so thread pool pressure is minimal. No configuration changes are required for this feature.

---

## 6. Rollout & Ops

### 6.1 Feature Flags & Config

- No new user‑facing feature flags are introduced; behavior is considered an internal hygiene improvement.
- If desired, an internal, non‑documented flag could later be added to toggle per‑publisher timing logs, but this is out of scope for this feature.

### 6.2 Migration / Backfill

- No data migrations or backfills are required (no schema changes).

### 6.3 Monitoring, Logging, Dashboards, Alerts

- **Logging**
  - New `publisher_publish` structured logs can be consumed alongside `workflow_timing` logs to analyze publish‑phase behavior.
- **Dashboards**
  - Future dashboards (out of scope for this feature) can chart `duration_ms` by `platform` to identify regressions or slow publishers.
- **Alerts**
  - Alerting on publisher latency/error rates can be built using `publisher_publish` logs, but configuration is deferred to a later observability‑focused change.

### 6.4 Capacity / Cost Estimates

- Thread pool utilization increases by at most the number of concurrent publishers for the brief duration of image resizing and blocking SDK calls; expected overhead is negligible.

---

## 7. Testing Strategy

### 7.1 Unit & Integration Tests

- **New Tests**
  - Add a dedicated test module (e.g., `test_publisher_async_throughput.py`) with:
    - **T1 – Concurrency Overlap Test**: Use dummy publisher implementations that record `start`/`end` times and sleep for a fixed duration; assert that their intervals overlap when run via `WorkflowOrchestrator.execute`, proving concurrency.
    - **T2 – Async Resizing Offload Test (Telegram/Instagram)**: Monkeypatch `ensure_max_width` to record the executing thread name via `threading.current_thread().name`, call the corresponding `publish` methods with network operations stubbed/mocked, and assert that resizing runs in a non‑main thread (indicating `asyncio.to_thread` usage).
    - **T3 – Per‑Publisher Logging Test**: Capture logs during a dummy publish and assert that `publisher_publish` entries are emitted with the expected fields.

- **Existing Tests**
  - Ensure all existing tests (especially publisher and workflow tests, plus performance telemetry tests) continue to pass without changes.

### 7.2 E2E Tests

- For environments with real or staging credentials, existing e2e tests that exercise the full workflow (or new optional ones) can be used to validate that multi‑platform latency does not regress significantly.

### 7.3 Performance & Regression Testing

- Use `publish_parallel_ms` and new per‑publisher logs in test runs to validate that enabling multiple publishers only slightly increases overall latency compared to the slowest publisher.

---

## 8. Risks & Alternatives

### 8.1 Risks

1. **R1 – Hidden Blocking Calls Remain**
   - Risk that other blocking work (e.g., future image processing or SDK usage) sneaks into publishers without using the new patterns.
   - *Mitigation*: Document async hygiene guidelines clearly and add tests that would catch serialized behavior in the publish phase.
2. **R2 – Overhead or Complexity from Threads**
   - `asyncio.to_thread` introduces additional threads; mis‑use could increase complexity or overhead.
   - *Mitigation*: Keep `to_thread` usage small and focused (image resizing, existing blocking SDKs) and avoid nesting or unnecessary wrappers.
3. **R3 – Logging Noise**
   - Per‑publisher logs may increase log volume.
   - *Mitigation*: Keep log payloads minimal, and allow operators to filter by `event` and `platform` as needed.

### 8.2 Alternatives Considered

1. **A1 – Introduce a Dedicated Publisher Worker Pool**
   - Considered implementing a separate worker pool or job queue for publisher work.
   - Rejected for this feature as overengineering: current concurrency via `asyncio.gather` + `asyncio.to_thread` suffices for existing scale.
2. **A2 – Rewrite Publishers to Use Fully Async SDKs Only**
   - Not feasible in the short term due to available libraries and compatibility constraints.
3. **A3 – Centralized Publisher Wrapper in Orchestrator**
   - Instead of pushing async hygiene into each publisher, orchestrator could wrap publisher calls in a generic `to_thread` wrapper.
   - Rejected because some publishers already use async SDKs (Telegram) and should not be forced into a thread; the per‑publisher implementation is the correct place to handle blocking vs async behavior.

---

## 9. Work Plan (High‑Level)

1. **M1 – Audit & Design Finalization**
   - Confirm all blocking operations in publishers and image utilities; validate the assumptions in this design.
2. **M2 – Implementation**
   - Add `ensure_max_width_async` and refactor Telegram/Instagram publishers to use it, plus per‑publisher timing logs.
3. **M3 – Testing**
   - Implement the tests outlined in §7 and ensure existing tests remain green.
4. **M4 – Documentation**
   - Update feature docs and, where appropriate, NFR/architecture docs to include the async hygiene guidelines.

---

## 10. Appendices

### 10.1 Glossary

- **Async‑Safe**: Code that does not perform long‑running blocking operations on the event loop thread, typically by delegating such operations to a thread pool or async SDKs.
- **Publisher**: A concrete implementation of the `Publisher` interface responsible for publishing content to a platform (Email/FetLife, Telegram, Instagram).
- **Throughput Hygiene**: Practices that ensure concurrency mechanisms (like `asyncio.gather`) deliver real performance benefits rather than being undermined by hidden blocking work.

### 10.2 References

- Feature Request: `docs_v2/08_Epics/08_01_Feature_Request/008_publisher-async-throughput-hygiene.md`
- Existing Performance & Telemetry Docs: `docs_v2/08_Epics/007-cross-cutting-performance-observability.md`
- Orchestrator Implementation: `publisher_v2/core/workflow.py`


