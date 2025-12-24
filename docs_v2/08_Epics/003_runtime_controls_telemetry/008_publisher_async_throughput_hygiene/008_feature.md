<!-- docs_v2/08_Epics/08_01_Feature_Request/008_publisher-async-throughput-hygiene.md -->

# Publisher Async Throughput Hygiene

**ID:** 008  
**Name:** publisher-async-throughput-hygiene  
**Status:** Shipped  
**Date:** 2025-11-20  
**Author:** Architecture Team  

## Summary
This feature focuses on ensuring that all publisher integrations (Email/FetLife, Telegram, Instagram) and related image processing are fully compatible with the async architecture and can scale throughput effectively.  
It reviews and standardizes how blocking SDK calls and heavy operations (e.g., network I/O, image resizing) are handled, so that the event loop remains responsive and parallel publishing delivers actual concurrency benefits.  
The outcome should be a set of clear patterns, refactors, and tests that keep publishers performant and robust as usage grows.

## Problem Statement
Publishers currently run in parallel using `asyncio.gather`, but individual implementations may rely on blocking SDKs or operations that are not always wrapped in non-blocking patterns (e.g., `asyncio.to_thread`).  
This can cause the event loop to stall, reduce effective concurrency, and lead to unpredictable latency, especially when multiple platforms are enabled.  
There is no feature-level specification that enforces async-safe patterns and throughput expectations across all publishers.

## Goals
- Audit and, where necessary, refactor publishers to ensure they do not block the event loop during network I/O or heavy CPU-bound work.  
- Clearly define and document async patterns for publishers, including when to use `asyncio.to_thread` and how to handle retries and timeouts.  
- Provide tests and simple benchmarks to validate that multi-platform publishing delivers the expected concurrency and latency characteristics.

## Non-Goals
- Adding new publishing platforms or changing platform-specific business rules (e.g., caption formatting, subject rules).  
- Introducing new queuing or scheduling systems for publishers in this feature.  
- Changing how dry-run or preview modes work from a functional perspective.

## Users & Stakeholders
- Primary users: CLI and web operators publishing to one or more platforms concurrently.  
- Stakeholders: Architecture team, developers maintaining publisher modules, operations teams monitoring performance and reliability.

## User Stories
- As an operator, I want multi-platform publishing to complete quickly even when several platforms are enabled, so that end-to-end latency remains within targets.  
- As a maintainer, I want publisher code to follow a clear async/non-blocking pattern, so that adding or updating publishers does not inadvertently degrade performance.  
- As an architect, I want confidence that the publishing step is not the bottleneck for throughput when external APIs are healthy.

## Acceptance Criteria (BDD-style)
- Given all three publishers (Telegram, Email, Instagram) are enabled and external services are healthy, when a typical image is published, then the total publish phase must not significantly exceed the slowest single publisher's latency under representative conditions.  
- Given a publisher uses a blocking SDK, when its operations are invoked, then they must be executed in a way that does not block the event loop (e.g., via `asyncio.to_thread` or an async equivalent), as verified by code inspection and tests.  
- Given tests for multi-platform publishing are run, when they measure basic timings under load, then they must show that enabling additional publishers increases latency modestly rather than linearly with the number of platforms.  
- Given preview and dry-run modes are exercised, when publishers are invoked under those modes, then their behavior must remain functionally unchanged while still adhering to async-safe patterns.

## UX / Content Requirements
- No user-facing UI changes are required; improvements are backend and performance-focused.  
- Documentation for configuration and behavior of publishers must remain accurate; any performance notes added should be brief and targeted to operators.  
- Error messages and logs from publishers should remain clear and consistent, but may include additional timing information where appropriate.

## Technical Constraints & Assumptions
- The architecture remains async-first; publishers must integrate cleanly with existing `asyncio`-based workflows.  
- External SDKs (SMTP, Telegram API, Instagram client, etc.) may not all be async-native and must be wrapped appropriately.  
- No new persistent queues or message brokers will be introduced as part of this feature; existing retry and error-handling strategies should be reused or minimally adjusted.

## Dependencies & Integrations
- Existing publisher modules (`services.publishers.email`, `telegram`, `instagram`) and any underlying third-party SDKs.  
- `WorkflowOrchestrator` publish phase and any helper utilities (e.g., image resizing in `utils.images`).  
- Logging and telemetry features (including cross-cutting performance and web telemetry, where relevant).

## Data Model / Schema
- No changes to persisted data models or schemas are expected.  
- Optional: additional in-memory structures or small helpers may be introduced to track per-publisher timings or statuses but should not persist beyond logs/metrics.  
- Sidecar and caption data models remain unchanged.

## Security / Privacy / Compliance
- Any changes to publisher implementations must continue to respect existing security and privacy constraints (e.g., not logging secrets, redacting sensitive data).  
- Network calls to external services must continue to use secure channels and authentication methods as currently configured.  
- PG-13 and content-safety requirements for captions remain unchanged and enforced at existing layers.

## Performance & SLOs
- The publish phase should generally meet the existing NFR target (e.g., all platforms completing within ~10 seconds typical), with multi-platform publishing not scaling linearly in latency.  
- CPU and event-loop utilization should remain within acceptable bounds; publisher work should not monopolize the event loop.  
- Any added overhead from wrapping blocking calls should be negligible compared to network round-trip times.

## Observability
- Metrics: optional simple measurements of per-publisher publish times and success/failure counts.  
- Logs & events: structured logs indicating per-platform publish duration and whether operations ran in a blocking or offloaded context (for debugging).  
- Dashboards/alerts: TODO; may include basic charts for per-platform latency and error rates derived from logs or metrics.

## Risks & Mitigations
- Refactoring publisher code could introduce regressions in platform-specific behavior — Mitigation: maintain or expand existing tests and, where feasible, perform targeted end-to-end tests against staging accounts.  
- Misuse of async wrappers could hide exceptions or complicate error handling — Mitigation: follow well-documented patterns and ensure exceptions are propagated or logged correctly.  
- Inconsistent handling across publishers could confuse future maintainers — Mitigation: document patterns in a shared location and apply them uniformly.

## Open Questions
- Do we need lightweight synthetic benchmarks for publishers (e.g., mocking external services) to track performance over time? — Proposed answer: likely yes; to be defined in follow-up tasks.  
- Should publisher timeouts and retry strategies be revisited in light of async hygiene work? — Proposed answer: TODO; assess once current behavior is fully documented.  
- Are there any legacy behaviors (e.g., email-specific quirks) that could be impacted by wrapping calls in `to_thread`? — Proposed answer: TODO; identify and test carefully.

## Milestones
- M1: Audit publishers and image-processing helpers for blocking operations and document findings.  
- M2: Implement async-safe patterns (e.g., `asyncio.to_thread` or async SDKs) and add targeted tests/benchmarks.  
- M3: Validate performance and behavior in staging/production-like environments; update documentation accordingly.

## Definition of Done
- All publishers are verified to be async-safe and non-blocking to the event loop, with tests demonstrating expected concurrency characteristics.  
- Publishing performance meets or improves on existing latency targets for multi-platform scenarios.  
- Documentation and developer guidelines for publisher async patterns are updated and agreed upon.  
- No regressions in functional behavior, security, or reliability are observed after rollout.

## Appendix: Source Synopsis
- Performance review highlighted that publishers and image processing can block the event loop and reduce effective concurrency.  
- Architecture constraints require async patterns and discourage blocking calls in async paths.  
- This feature request consolidates the need to audit, refactor, and validate publisher async behavior into a coherent piece of work.


