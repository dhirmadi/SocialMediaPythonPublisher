<!-- docs_v2/08_Epics/08_01_Feature_Request/017_multi-platform-publishing.md -->

# Multi-Platform Publishing Engine

**ID:** 017  
**Name:** multi-platform-publishing  
**Status:** Shipped  
**Date:** 2025-11-22  
**Author:** Retroactive Documentation  

## Summary
The core publishing logic that allows the system to push a single piece of content (Image + Caption) to multiple distinct platforms (Telegram, Instagram, Email) simultaneously, robustly, and in parallel.

## Problem Statement
We need to support an arbitrary number of destination platforms. Publishing sequentially is slow (latency adds up) and brittle (if the first fails, the second might not run). Without a unified interface, the Orchestrator would become a tangle of platform-specific `if/else` logic, making it hard to add new integrations or maintain existing ones.

## Goals
- **Polymorphism:** A common `Publisher` interface that abstracts away platform-specific APIs.
- **Concurrency:** Publish to all enabled platforms in parallel to minimize total workflow time.
- **Isolation:** A failure in one platform (e.g., Instagram login error) must not stop others (e.g., Email) from succeeding.
- **Extensibility:** Adding a new platform (e.g., Bluesky) should only require adding a new class file, not modifying the core orchestrator.

## Non-Goals
- **Scheduling:** The engine publishes "now"; scheduling is handled by external triggers (Cron, Heroku Scheduler).
- **Social Interaction:** Reading comments or DMs is out of scope; this is a broadcast-only system.
- **GUI Configuration:** Enabling/disabling platforms is done via config files, not a UI.

## Users & Stakeholders
- **User:** Who wants their content distributed to their audience on Telegram, Instagram, and FetLife simultaneously.
- **Operator:** Who wants to enable/disable platforms easily (e.g., "Turn off Instagram while the API is broken").
- **Developer:** Who wants to implement a new publisher (e.g., Mastodon) by just subclassing `Publisher`.

## User Stories
- As a user, I want my photo to appear on Telegram, Instagram, and FetLife (via Email) at roughly the same time.
- As an operator, I want to disable a specific platform via config without deploying new code.
- As the system, I want to consider the workflow "Successful" if *at least one* platform accepted the post, so that I can archive the image.

## Acceptance Criteria (BDD-style)
- **Given** multiple enabled publishers, **when** `publish` is called, **then** they must execute concurrently (not sequentially).
- **Given** one publisher fails (raises exception) and another succeeds, **when** the workflow completes, **then** the result must indicate partial success and the image must be archived.
- **Given** a disabled publisher, **when** the workflow runs, **then** that publisher's `publish` method must not be called.
- **Given** a generic `Publisher` interface, **when** a concrete implementation is instantiated, **then** it must provide a `platform_name` and `is_enabled` property.

## Technical Constraints & Assumptions
- **Async I/O:** All publish methods must be `async`. Blocking libraries (like `smtplib` or `instagrapi`) must be wrapped in `asyncio.to_thread`.
- **Error Boundaries:** Exceptions must be caught per-publisher and returned as error results, not propagated to crash the loop.
- **Configuration:** Enablement flags must be read from `ApplicationConfig` at runtime.

## Dependencies & Integrations
- **Publisher Implementations:** Feature 014 covers the specific complex logic for Instagram/Email; this feature covers the engine/interface.
- **Orchestrator:** The `WorkflowOrchestrator` is the consumer of this engine.
- **Asyncio:** The Python concurrency library used.

## Risks & Mitigations
- **Risk:** A slow publisher delays the entire batch.  
  **Mitigation:** `asyncio.gather` waits for all, but timeouts can be applied (future improvement) or handled by the underlying library limits.
- **Risk:** Shared state between publishers.  
  **Mitigation:** Publishers are instantiated independently and should not share state.
