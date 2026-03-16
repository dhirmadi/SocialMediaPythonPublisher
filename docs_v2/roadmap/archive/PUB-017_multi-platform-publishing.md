# PUB-017: Multi-Platform Publishing Engine

| Field | Value |
|-------|-------|
| **ID** | PUB-017 |
| **Category** | Publishing |
| **Priority** | INF |
| **Effort** | M |
| **Status** | Done |
| **Dependencies** | — |

## Problem

We need to support an arbitrary number of destination platforms. Publishing sequentially is slow (latency adds up) and brittle (if the first fails, the second might not run). Without a unified interface, the Orchestrator would become a tangle of platform-specific `if/else` logic, making it hard to add new integrations or maintain existing ones.

## Desired Outcome

A common `Publisher` interface that abstracts away platform-specific APIs. Publish to all enabled platforms in parallel to minimize total workflow time. A failure in one platform (e.g., Instagram login error) must not stop others (e.g., Email) from succeeding. Adding a new platform (e.g., Bluesky) should only require adding a new class file, not modifying the core orchestrator.

## Scope

- Polymorphic `Publisher` interface with `platform_name` and `is_enabled` properties
- Concurrent execution via `asyncio.gather` (not sequential)
- Per-publisher error boundaries: exceptions caught and returned as error results, not propagated
- Enablement flags read from `ApplicationConfig` at runtime

## Acceptance Criteria

- AC1: Given multiple enabled publishers, when `publish` is called, then they must execute concurrently (not sequentially)
- AC2: Given one publisher fails (raises exception) and another succeeds, when the workflow completes, then the result must indicate partial success and the image must be archived
- AC3: Given a disabled publisher, when the workflow runs, then that publisher's `publish` method must not be called
- AC4: Given a generic `Publisher` interface, when a concrete implementation is instantiated, then it must provide a `platform_name` and `is_enabled` property

## Implementation Notes

- All publish methods must be `async`; blocking libraries (smtplib, instagrapi) wrapped in `asyncio.to_thread`
- Exceptions caught per-publisher and returned as error results
- Workflow considers "Successful" if at least one platform accepted the post (image archived)

## Related

- [Original feature doc](../../08_Epics/000_v2_foundation/017_multi_platform_publishing/017_feature.md) — full historical detail
