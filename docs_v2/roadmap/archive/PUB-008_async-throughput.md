# PUB-008: Publisher Async Throughput Hygiene

| Field | Value |
|-------|-------|
| **ID** | PUB-008 |
| **Category** | Publishing |
| **Priority** | INF |
| **Effort** | S |
| **Status** | Done |
| **Dependencies** | PUB-017 |

## Problem

Publishers run in parallel using `asyncio.gather`, but individual implementations may rely on blocking SDKs or operations not wrapped in non-blocking patterns (e.g., `asyncio.to_thread`). This can stall the event loop, reduce effective concurrency, and lead to unpredictable latency when multiple platforms are enabled.

## Desired Outcome

All publisher integrations (Email, Telegram, Instagram) and related image processing are fully async-safe. Blocking SDK calls are wrapped in `asyncio.to_thread`. Multi-platform publishing delivers actual concurrency benefits with predictable latency.

## Scope

- Audit and refactor publishers to ensure no event loop blocking during network I/O or CPU-bound work
- Define and document async patterns for publishers (when to use `asyncio.to_thread`, retry/timeout handling)
- Provide tests and benchmarks to validate concurrency and latency characteristics
- Preview and dry-run modes remain functionally unchanged while using async-safe patterns

## Acceptance Criteria

### AC1: Concurrent publishing latency

Given all three publishers are enabled, when a typical image is published, then the total publish phase must not significantly exceed the slowest single publisher's latency.

### AC2: No event loop blocking

Given a publisher uses a blocking SDK, when its operations are invoked, then they must be executed via `asyncio.to_thread` or async equivalent, verified by code inspection and tests.

### AC3: Sublinear latency scaling

Given tests for multi-platform publishing, when they measure timings under load, then enabling additional publishers increases latency modestly rather than linearly.

### AC4: Preview/dry-run unchanged

Given preview and dry-run modes are exercised, when publishers are invoked, then behavior remains functionally unchanged while adhering to async-safe patterns.

## Implementation Notes

- Publishers in `publisher_v2/src/publisher_v2/services/publishers/`
- Blocking calls wrapped with `asyncio.to_thread`
- Tests under `publisher_v2/tests/`

## Related

- [Original feature doc](../../08_Epics/003_runtime_controls_telemetry/008_publisher_async_throughput_hygiene/008_feature.md) — full historical detail
- [PUB-017: Multi-Platform Publishing](PUB-017_multi-platform-publishing.md) — the publishing engine this item optimizes
