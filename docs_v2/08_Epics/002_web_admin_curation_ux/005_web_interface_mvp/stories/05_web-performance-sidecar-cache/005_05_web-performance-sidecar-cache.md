<!-- docs_v2/08_Epics/08_04_ChangeRequests/005/004_web-performance-sidecar-cache.md -->

# Web Performance & Sidecar Cache — Change Request

**Feature ID:** 005  
**Change ID:** 005-004  
**Name:** web-performance-sidecar-cache  
**Status:** Shipped  
**Date:** 2025-11-20  
**Author:** Architecture Team  
**Parent Feature Design:** docs_v2/08_Epics/08_02_Feature_Design/005_web-interface-mvp_design.md  

## Summary
This change refines the Web Interface MVP to improve responsiveness and efficiency when browsing, analyzing, and publishing images via the web UI.  
It introduces short-lived caching for Dropbox image listings, sidecar-first behavior for analysis endpoints, and parallelization of independent Dropbox calls, all while maintaining existing contracts.  
The goal is to keep `/api/images/random` and `/api/images/{filename}/analyze` within tighter latency budgets, especially under repeated use, without altering core business logic.

## Problem Statement
The current web design always lists images from Dropbox on each random-image request, recomputes hashes from full image downloads, and re-runs OpenAI analysis even when a complete sidecar already exists.  
Independent Dropbox operations (temp links, sidecar reads, metadata) are performed sequentially, which adds round-trip latency.  
As a result, common web flows feel slower than necessary and overuse external APIs.

## Goals
- Reduce latency of `/api/images/random` by caching the image list and avoiding redundant downloads purely for hash computation.  
- Allow `/api/images/{filename}/analyze` to reuse existing sidecars as a cache for analysis/captions when appropriate, while still supporting explicit re-analysis.  
- Parallelize safe, independent Dropbox calls in the web service layer to minimize wall-clock time for each request.  

## Non-Goals
- Changing the structure or semantics of the web API request/response payloads.  
- Introducing new persistent stores or replacing Dropbox as the source of truth.  
- Modifying CLI-only behavior or the core workflow’s selection and dedup logic (handled in separate features).

## Affected Feature & Context
- **Parent Feature:** Web Interface MVP  
- **Relevant Sections:**  
  - §3. Requirements – FR2 (Random Image Selection), FR3 (AI Analysis & Caption), FR5 (Sidecar Reading).  
  - §4. Architecture & Design – `WebImageService`, sidecar parser, and endpoint flows.  
  - §5. Detailed Flow – Flows 1–3 for random image, analyze, and publish.  
- This change keeps the overall architecture intact but optimizes data access patterns and introduces a sidecar-aware analysis path, leveraging existing sidecar semantics from Feature 001.  
- Sidecar cache semantics (when to reuse vs. refresh, and how to fall back to OpenAI) follow the canonical definition in `docs_v2/08_Epics/08_04_ChangeRequests/001/001_sidecars-as-ai-cache.md`.

## User Stories
- As an admin using the web UI, I want “Next image” to feel fast even when I click it repeatedly, so that browsing my Dropbox image folder is smooth.  
- As an admin, I want re-analyzing images that already have sidecars to be nearly instant, so I can review prior work without paying the full AI cost again.  
- As an operator, I want the web layer to use Dropbox and OpenAI efficiently, so that latency and usage costs remain under control as my library grows.

## Acceptance Criteria (BDD-style)
- Given multiple sequential calls to `/api/images/random` within a short time window, when the underlying Dropbox folder has not changed, then the service should use a cached image list and avoid re-listing from Dropbox on every request.  
- Given an image that already has a valid sidecar, when `/api/images/{filename}/analyze` is called without a force-refresh flag, then the service should reconstruct analysis/caption data from the sidecar without performing a new OpenAI analysis/caption call.  
- Given any image (with or without sidecar), when `/api/images/{filename}/analyze` is called with an explicit force-refresh flag, then the service must perform a fresh analysis/caption cycle and overwrite the sidecar as described in the parent features.  
- Given a request to `/api/images/random` or `/api/images/{filename}/analyze`, when independent Dropbox operations are required (e.g., get temp link, sidecar, metadata), then they should be executed in parallel where safe, and the overall response time must not regress compared to the sequential baseline.

## UX / UI Requirements
- No visual changes are strictly required, but the UI must continue to function correctly with faster responses and cached behavior.  
- If a force-refresh option is exposed in the UI (e.g., “Re-analyze (force AI)” button), it must be clearly differentiated from the normal analyze action and gated by existing admin/auth controls.  
- Any loading indicators or status messages should remain accurate even when operations complete more quickly.

## Technical Notes & Constraints
- Implement a short-lived, in-memory cache for the Dropbox image list inside `WebImageService`, with a configurable or hard-coded TTL (e.g., 30–60 seconds) and safe invalidation semantics.  
- Avoid recomputing hashes from full image downloads purely for display; prefer Dropbox metadata (e.g., `content_hash`) or make the hash optional in responses.  
- Extend the analyze flow to first attempt sidecar parsing (using the existing sidecar parser and semantics from Feature 001) and only call OpenAI when sidecar reuse is disabled, sidecar is missing/invalid, or force-refresh is requested.  
- Use `asyncio.gather` or equivalent to parallelize independent Dropbox calls, preserving error handling and retries from `DropboxStorage`.  
- Respect all existing authentication, authorization, and dry/preview semantics described in the parent design.  
- This change is additive and must not alter existing web API contracts; by default, behavior remains functionally identical while responses become faster under repeated use.

## Risks & Mitigations
- Stale cache could serve images that no longer exist or miss new uploads — Mitigation: keep TTL short, handle 404s gracefully, and refresh on cache miss or error.  
- Sidecar parsing issues could cause inconsistent behavior between cached and fresh analysis — Mitigation: rely on robust parsing, log problems, and automatically fall back to fresh AI calls when sidecars are not trustworthy.  
- Parallelization might complicate error handling or logging — Mitigation: maintain structured logs per sub-call and ensure exception handling remains explicit and test-covered.

## Open Questions
- What is an appropriate default TTL for the image-list cache, and should it be configurable via web-related config? — Proposed answer: start with a small fixed TTL (e.g., 30s) and add config only if needed.  
- How should the force-refresh flag be represented at the API level (query parameter vs. request body)? — Proposed answer: prefer a simple, documented query parameter (e.g., `?force_refresh=true`).  
- Should the web layer expose any explicit indication (e.g., response field) that data was served from cache vs. fresh analysis? — Proposed answer: TODO; might be useful for debugging but should not clutter the user experience.


