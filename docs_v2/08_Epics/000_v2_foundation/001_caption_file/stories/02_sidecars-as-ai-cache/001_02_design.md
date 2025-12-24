<!-- docs_v2/08_Epics/08_04_ChangeRequests/001/001_design.md -->

# Sidecars as AI Cache — Change Design

**Feature ID:** 001  
**Change ID:** 001-001  
**Parent Feature:** Stable Diffusion Caption File  
**Design Version:** 1.0  
**Date:** 2025-11-20  
**Status:** Design Review  
**Author:** TODO  
**Linked Change Request:** docs_v2/08_Epics/08_04_ChangeRequests/001/001_sidecars-as-ai-cache.md  
**Parent Feature Design:** docs_v2/08_Epics/08_02_Feature_Design/001_captionfile_design.md  

## 1. Summary

- Problem & context: The captionfile feature already writes rich `.txt` sidecars (SD caption + metadata), but all callers still recompute analysis and captions via OpenAI on every request. This wastes latency and cost and leaves “sidecars as cache” semantics implicit instead of codified.  
- Goals & Non-goals: This change formalizes the sidecar as a cacheable representation of AI analysis/caption data and introduces a canonical, reusable sidecar-read path for reconstructing that data, without changing the on-disk sidecar format or archive behavior. Immediate adoption focuses on the web layer and future preview flows; publisher and core workflow semantics remain as in the parent feature.

## 2. Context & Assumptions

- Current behavior (affected parts):
  - `utils.captions.build_caption_sidecar` writes sidecars with first-line `sd_caption` and Phase1/Phase2 metadata blocks.
  - `services.storage.DropboxStorage.write_sidecar_text` uploads/overwrites `.txt` beside the image; `archive_image` best-effort moves the sidecar with the image.
  - `web.sidecar_parser.parse_sidecar_text` parses `sd_caption` and metadata into a tuple `(sd_caption, metadata_dict)` but does not provide higher-level “rehydrate analysis” semantics.
  - `web.service.WebImageService`:
    - `get_random_image` opportunistically reads sidecars for display.
    - `analyze_and_caption` always runs fresh analysis + caption via OpenAI, then writes a new sidecar; no sidecar-based caching.
  - `core.workflow.WorkflowOrchestrator` always runs OpenAI analysis and caption when not in preview, regardless of sidecar presence.
- Constraints inherited from the parent feature:
  - Sidecar format and field names from Feature 001 are the single source of truth; this change cannot alter the writer format.
  - SD caption generation remains best-effort and non-blocking; missing or invalid `sd_caption` must not break core flows.
  - Dropbox remains the only persistent backing store; no additional databases or caches.
- Dependencies:
  - `DropboxStorage` for reading/writing/moving sidecars.
  - `ImageAnalysis` model and metadata builders in `utils.captions`.
  - Web layer components (`WebImageService`, `parse_sidecar_text`) as the first adopters of caching semantics.

## 3. Requirements

### 3.1 Functional Requirements

- **CR1:** Define canonical semantics for treating an existing sidecar as an authoritative cache of SD caption and expanded analysis metadata, including when to trust it and when to fall back to OpenAI.  
- **CR2:** Provide a reusable helper in the web layer that can reconstruct a minimal analysis/caption view from sidecar contents without issuing OpenAI calls.  
- **CR3:** Ensure callers have a clear mechanism to bypass sidecar cache and force a fresh analysis/caption run (e.g., via an explicit “force refresh” flag at the API or service level), with safe default behavior.  
- **CR4:** Preserve existing sidecar writing and archive behavior; reading from cache must never change when and how sidecars are created or moved.

### 3.2 Non-Functional Requirements

- Sidecar parsing must be robust and defensive: malformed or partial sidecars should not crash callers and must automatically fall back to fresh AI analysis.  
- Performance should improve for cache hits (no OpenAI calls), but cache misses must not materially regress existing latency.  
- Logging must make cache usage visible (e.g., `cache_hit=true/false` fields) without leaking secrets.  
- No new persistent storage or background daemons; all caching remains on-demand and stateless beyond Dropbox sidecars.  

## 4. Architecture & Design (Delta)

### 4.1 Current vs. Proposed

- Current:
  - Sidecars are always written by the workflow/web paths after SD caption generation, but never used to avoid future AI calls.  
  - Web and CLI flows treat sidecars as a write-only artifact; “cache” semantics are informal and duplicated in tests/docs only.  
- Proposed:
  - Treat the existing sidecar format as the canonical cache for SD caption and selected analysis metadata.  
  - Extend `web.sidecar_parser` with a small helper that:
    - Takes `(sd_caption, metadata)` produced by `parse_sidecar_text`.
    - Produces a lightweight “rehydrated” view suitable for callers (e.g., caption, sd_caption, key tags/fields from metadata) without constructing a full `ImageAnalysis` instance.
  - Introduce a `force_refresh: bool` flag at the `WebImageService` level (and, by extension, web API) to control whether sidecar cache is used or bypassed; the default is to reuse sidecar when valid.

### 4.2 Components & Responsibilities

- `publisher_v2.web.sidecar_parser` — Remains the canonical reader for caption sidecars; gains a helper such as `rehydrate_from_sidecar(text: str) -> dict[str, Any]` or similar to encapsulate cache semantics (including trust/fallback rules).  
- `publisher_v2.web.service.WebImageService` — Becomes the first supported caller that can:  
  - Prefer sidecar-based reconstruction for analysis/caption responses when not forcing refresh.  
  - Fall back to OpenAI analysis + caption when the sidecar is missing, invalid, or force-refresh is requested.  
- `publisher_v2.core.workflow.WorkflowOrchestrator` — No behavioral change in this story; may later reuse the same semantics in preview flows but remains out of scope here except for documenting compatibility expectations.  
- Tests under `publisher_v2/tests/web/` — Extended to cover sidecar cache behavior and force-refresh semantics for web-level service methods.

### 4.3 Data & Contracts

- No changes to the on-disk sidecar format produced by `build_caption_sidecar`.  
- No changes to external JSON response schemas for web or CLI.  
- Internal contracts:
  - Sidecar-derived view will expose at least:
    - `sd_caption` (from first line).  
    - Optional `caption` from metadata (if present).  
    - Optional structured fields (e.g., `tags`, `aesthetic_terms`, `moderation`) derived from metadata for internal use.  
  - If metadata is missing or incomplete, callers must still receive a consistent shape (e.g., `caption: None`, `sd_caption: <text or None>`).

### 4.4 Error Handling & Edge Cases

- If sidecar content is empty, non-UTF-8, or cannot be parsed:
  - Treat as cache miss: callers must proceed with fresh analysis/caption generation.  
  - Log a structured warning with `sidecar_parse_error=true` and a sanitized reason.  
- If sidecar is present but missing some fields:
  - Use whatever can be safely reconstructed (e.g., `sd_caption` only); leave missing fields as `None` or empty lists.  
  - Do not attempt to “fix” or rewrite the sidecar in this change.  
- Force refresh:
  - When `force_refresh=True`, callers must skip sidecar parsing entirely for that request and perform a full AI analysis and sidecar rewrite as per the parent feature.  

### 4.5 Security, Privacy, Compliance

- Auth and authorization rules remain unchanged; only already-authorized pathways can invoke cache behavior.  
- Sidecar content is already limited to PG-13 SD captions and non-PII metadata as defined in Feature 001; this change does not broaden data collection.  
- Logs must not include full `sd_caption` or sensitive metadata fields; they should only record high-level cache-hit state and identifiers (e.g., filename).  

## 5. Detailed Flow

- Main success path (cache hit, web service):
  1. Caller (e.g., web `/api/images/{filename}/analyze`) invokes `WebImageService` with `force_refresh=False`.  
  2. `WebImageService` attempts to download the sidecar `.txt` via `DropboxStorage.download_image`.  
  3. On success, `parse_sidecar_text` extracts `sd_caption` and metadata.  
  4. New helper constructs a sidecar-derived view (caption, sd_caption, key metadata), marking this as a cache hit in logs.  
  5. Service returns an analysis/caption response assembled from the sidecar-derived view without calling OpenAI.  
- Edge path (cache miss or invalid sidecar):
  1. Sidecar is absent, unreadable, or parse helper returns insufficient data.  
  2. `WebImageService` logs a cache miss and runs the existing analysis + caption pipeline via `AIService` and caption generator.  
  3. Sidecar is (re)written using the parent feature’s logic; response is built from fresh analysis/caption.  
- Edge path (force refresh):
  1. Caller invokes `WebImageService` with `force_refresh=True`.  
  2. Service skips sidecar parsing and directly runs the OpenAI-based pipeline.  
  3. A new sidecar overwrites the previous contents; logs indicate a forced refresh.

## 6. Testing Strategy (for this Change)

- Unit tests:
  - `web/test_sidecar_parser.py`: add tests covering the new helper semantics for well-formed, partial, and malformed sidecars.  
  - `web/test_web_service.py`: tests for `WebImageService` behavior when given existing sidecars vs. missing/invalid ones (cache hit/miss), and when `force_refresh` is requested (behavior identical to fresh analysis).  
- Integration tests:
  - `web_integration/test_web_endpoints.py`: extend tests (or add new cases) to verify that, with pre-populated sidecars and without a refresh flag, `/api/images/{filename}/analyze` returns quickly and without issuing new OpenAI calls (validated via mocks/spies).  
- E2E / manual checks:
  - Run the web UI against a Dropbox folder with pre-existing sidecars; verify that repeated analyze operations on the same image are fast and do not trigger additional AI requests, while an explicit “re-analyze” action (once wired in via later CRs) forces a fresh run.

## 7. Risks & Alternatives

- Risks:
  - Treating malformed sidecars as cache hits could surface stale or incorrect data — mitigated by defensive parsing and automatic fallback to fresh analysis on parse anomalies.  
  - Confusion about when data is refreshed vs. cached — mitigated by clear logging and, in follow-up UI work, subtle indicators or timestamps.  
  - Over-coupling cache semantics to the web layer — mitigated by keeping the parsing logic isolated and documented so future CLI/preview adopters can reuse it.  
- Alternatives:
  - Introduce a separate “cache” service or module instead of extending `sidecar_parser` — rejected for now as overengineering for a single sidecar format and first web-only consumer.  
  - Store cached analysis in a database — rejected; violates repo constraints and offers little benefit over existing sidecars.  

## 8. Work Plan (Scoped)

- Define and document sidecar cache semantics in code comments and this design, using Feature 001 structures as the source of truth.  
- Extend `publisher_v2.web.sidecar_parser` with a helper that converts parsed sidecar data into a structured view suitable for callers.  
- Update `publisher_v2.web.service.WebImageService` to optionally use cached sidecar data for analysis/caption responses when available and not forcing refresh (keeping full integration of force-refresh flag at the API layer for CR 005-004).  
- Add unit and integration tests under `publisher_v2/tests/web` and `publisher_v2/tests/web_integration` to exercise cache-hit, cache-miss, and force-refresh paths.  
- Update relevant docs (if needed) to reference `sidecars-as-ai-cache` as the canonical semantics for downstream changes (e.g., CR 005-004).

## 9. Open Questions

- How “complete” must sidecar metadata be to qualify as a cache hit (e.g., is `sd_caption` alone sufficient)? — Proposed answer: `sd_caption` alone is acceptable; metadata is best-effort enrichment.  
- Should we attempt to reconstruct a full `ImageAnalysis` instance from sidecar metadata for some callers? — Proposed answer: out of scope for this change; callers currently need only caption/sd_caption plus a small set of fields.  
- Where should the eventual force-refresh API surface live (query param vs. request body vs. header) for web endpoints? — Proposed answer: align with CR 005-004; likely a simple `?force_refresh=true` query parameter.


