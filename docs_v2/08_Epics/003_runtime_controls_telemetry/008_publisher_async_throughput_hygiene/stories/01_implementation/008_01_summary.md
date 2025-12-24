# Publisher Async Throughput Hygiene

**Feature ID:** publisher-async-throughput-hygiene  
**Status:** Shipped  
**Date Completed:** 2025-11-20  
**Code Branch / PR:** TODO  

## Summary
This feature audits and hardens the async behavior of existing publishers (Email/FetLife, Telegram, Instagram) so that multi-platform publishing fully benefits from asyncio-based concurrency without blocking the event loop. It introduces a small async image helper, standardizes thread-offloading for blocking SDKs, and adds per-publisher telemetry plus tests to validate concurrent execution characteristics.

## Goals
- Ensure publisher implementations do not block the event loop with heavy CPU work or blocking SDK calls.
- Make image resizing and other synchronous preprocessing safe to use from async publisher flows.
- Provide per-publisher timing telemetry to support performance analysis and observability.
- Add tests that validate concurrent publisher behavior and guard against regressions.

## Non-Goals
- Adding new publisher platforms or changing existing platform-specific business rules.
- Introducing new queues, schedulers, or background workers for publisher execution.
- Changing preview/dry-run semantics, AI behavior, or sidecar data models.

## User Value
Operators benefit from faster, more predictable end-to-end publish latency when multiple platforms are enabled, because the publish phase is less likely to be bottlenecked by hidden blocking work. Maintainers gain clear patterns for writing async-safe publishers and observable timing data to diagnose issues, reducing the risk of accidental performance regressions as integrations evolve.

## Technical Overview
- **Core flow**: `WorkflowOrchestrator.execute` remains the single orchestrator, still publishing via `asyncio.gather` and emitting `workflow_timing` logs with `publish_parallel_ms`. Publisher implementations are updated to be event-loop-friendly without changing their external behavior or the orchestrator contract.
- **Key components touched**:
  - `utils.images`: adds `ensure_max_width_async` that wraps the existing synchronous resize helper in `asyncio.to_thread`.
  - `services.publishers.email`: continues to send via SMTP in a thread pool, now emitting per-publisher timing logs.
  - `services.publishers.telegram`: uses the async resize helper before calling the async Telegram Bot client, and emits timing logs.
  - `services.publishers.instagram`: uses the async resize helper and continues to run Instagrapi client operations in a thread, with added timing logs.
- **Flags / config**: No new user-visible flags or config fields are added; all behavior changes are internal hygiene and observability improvements.
- **Data model updates**: No persisted schema changes; the only additions are structured log entries for `publisher_publish` events containing platform, duration, success, and error fields.
- **External API usage**: Existing SMTP, Telegram Bot, and Instagrapi integrations are preserved; they are simply wrapped more carefully to avoid event-loop blocking.

## Implementation Details
- **Key functions/classes added or modified**:
  - Added `ensure_max_width_async(image_path: str, max_width: int) -> str` in `utils.images` as an `asyncio.to_thread` wrapper around `ensure_max_width`.
  - Added `log_publisher_publish(logger, platform, start, success, error=None)` in `utils.logging` to emit structured `publisher_publish` logs with measured durations.
  - Updated `EmailPublisher.publish` to record start time, continue sending via `asyncio.to_thread`, and log success/failure via `log_publisher_publish`.
  - Updated `TelegramPublisher.publish` to resize via `ensure_max_width_async`, then send using the async Telegram client, logging timing and outcomes.
  - Updated `InstagramPublisher.publish` to resize via `ensure_max_width_async` and continue using `asyncio.to_thread` for Instagrapi, with added timing logs.
- **Migrations**: None; no database or schema changes.
- **Error handling**: Publisher exceptions are still caught and mapped to `PublishResult(success=False, error=...)`, and any uncaught exceptions from `asyncio.gather` continue to be converted into failure `PublishResult`s by the orchestrator. Logging helpers choose log level based on success/failure and never include secrets.
- **Performance + reliability considerations**: Blocking image operations and SDK calls now consistently run in the default thread pool, preserving event-loop responsiveness even under multi-platform publishing. Additional overhead from thread dispatch and logging is minimal compared to network I/O.
- **Security / privacy notes**: New logs use existing sanitization and avoid including tokens, passwords, or user-identifying data; they only record platform names, durations, success flags, and high-level error strings.

## Testing
The feature adds `test_publisher_async_throughput.py` to validate async behavior and logging:
- A concurrency test uses two dummy publishers that sleep for a fixed delay, asserting that their time intervals overlap when executed via `WorkflowOrchestrator`, confirming concurrent execution via `asyncio.gather`.
- A test for `ensure_max_width_async` monkeypatches the synchronous helper to ensure it is invoked exactly once, verifying the async wrapper delegates correctly.
- A logging test uses a dummy publisher and `caplog` to assert that `publisher_publish` structured log entries are emitted with the expected event marker.
All existing tests continue to pass, ensuring no regressions in preview/dry-run behavior, AI flows, or sidecar handling.

## Rollout Notes
- **Feature flags**: No new flags; changes are always-on internal improvements.
- **Monitoring / logs**: Operators can now inspect `publisher_publish` logs alongside existing `workflow_timing` entries to analyze per-platform latency and failures. Future dashboards and alerts can be built on these events without further code changes.
- **Backout strategy**: If needed, reverting this feature involves removing the async helper and timing/logging changes in publishers and `utils.logging`, restoring the prior synchronous resize calls and publisher implementations.

## Artifacts
- **Design doc**: docs_v2/08_Epics/08_02_Feature_Design/008_publisher-async-throughput-hygiene_design.md
- **Plan**: docs_v2/08_Epics/08_03_Feature_plam/008_publisher-async-throughput-hygiene_plan.yaml
- **PR**: TODO

## Final Notes
This feature brings publisher implementations in line with the project’s async-first architecture, reducing the risk that hidden blocking work undermines concurrency as more platforms are enabled. Future improvements could include lightweight synthetic benchmarks and dashboards over `publisher_publish` logs, as well as extending the same async hygiene patterns to any new publisher modules introduced later. 


