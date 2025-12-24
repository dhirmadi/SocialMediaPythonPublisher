<!-- docs_v2/08_Epics/08_04_ChangeRequests/005/004_design.md -->

# Web Performance & Sidecar Cache — Change Design

**Feature ID:** 005  
**Change ID:** 005-004  
**Parent Feature:** Web Interface MVP  
**Design Version:** 1.0  
**Date:** 2025-11-20  
**Status:** Design Review  
**Author:** TODO  
**Linked Change Request:** docs_v2/08_Epics/08_04_ChangeRequests/005/004_web-performance-sidecar-cache.md  
**Parent Feature Design:** docs_v2/08_Epics/08_02_Feature_Design/005_web-interface-mvp_design.md  

## 1. Summary

- Problem & context: The current web interface lists images from Dropbox and performs AI analysis sequentially on every request, even when sidecars already exist. This leads to unnecessary latency and external API usage, especially when repeatedly requesting random images or re-analyzing known files.  
- Goals & Non-goals: This change introduces a short-lived in-memory cache for Dropbox image listings, adds sidecar-first behavior for analysis in the web layer (reusing the canonical semantics from CR 001-001), and parallelizes safe Dropbox calls in random/analyze flows, all while preserving existing HTTP contracts and auth semantics.

## 2. Context & Assumptions

- Current behavior (affected parts):
  - `web.service.WebImageService.get_random_image`:
    - Calls `DropboxStorage.list_images` on every request.  
    - Downloads the selected image to compute SHA256.  
    - Optionally downloads and parses a sidecar for display, but does not cache the image list.  
  - `web.service.WebImageService.analyze_and_caption`:
    - Validates the file by calling `get_temporary_link`.  
    - Always runs OpenAI vision analysis + caption generation, then writes a new sidecar.  
    - Does not reuse existing sidecars as an AI cache.  
  - Web endpoints in `web.app` call these service methods directly; all Dropbox calls inside a request are performed serially.  
- Constraints inherited from the parent feature:
  - Dropbox remains the sole persistent store; no databases or new cache layers may be introduced.  
  - Web API contracts (request/response shapes) must remain unchanged.  
  - Auth (token/basic, admin cookie) and dry/preview semantics must not be weakened.  
- Dependencies:
  - `DropboxStorage` for listing images, obtaining temporary links, and downloading sidecars.  
  - `AIService`, sidecar builders (`utils.captions`), and sidecar parser (`web.sidecar_parser`).  
  - Canonical “sidecars as cache” semantics defined by CR 001-001.

## 3. Requirements

### 3.1 Functional Requirements

- **CR1:** Add a short-lived, in-memory cache of the Dropbox image list inside the web service layer, used by `/api/images/random` to avoid re-listing on every request when the underlying folder is unchanged.  
- **CR2:** Allow `/api/images/{filename}/analyze` to reuse existing sidecars as a cache for analysis/caption data when `force_refresh` is not requested, using the canonical cache semantics from CR 001-001.  
- **CR3:** Support a `force_refresh` flag on the analyze endpoint that triggers a full AI analysis + caption generation and sidecar overwrite, regardless of cache state.  
- **CR4:** Parallelize independent Dropbox operations (e.g., temp link + sidecar download, or temp link + hash computation) within a single request using asyncio primitives, without changing external behavior.  

### 3.2 Non-Functional Requirements

- Web endpoints must meet or improve existing latency targets, with particular focus on repeated `/api/images/random` and `/api/images/{filename}/analyze` calls.  
- The image list cache must be bounded in lifetime (fixed TTL) and safe under dyno restart (cache loss is acceptable; correctness must not depend on the cache).  
- Caching and parallelization must be fully backward compatible: in the worst case (e.g., cache disabled or sidecars missing), behavior must match the current implementation.  
- Logging must indicate when cache and parallel paths are used (e.g., `image_list_cache_hit`, `sidecar_cache_hit`), aiding debugging and future telemetry work.  

## 4. Architecture & Design (Delta)

### 4.1 Current vs. Proposed

- Current:
  - Each `/api/images/random` request triggers a fresh `list_images` call and then downloads one image to compute its SHA256; all Dropbox calls occur sequentially.  
  - `/api/images/{filename}/analyze` always runs fresh OpenAI analysis and caption generation, even if a valid sidecar exists.  
  - Web service uses sidecars only for display in `get_random_image`, not as an authoritative cache.  
- Proposed:
  - Introduce an in-memory image list cache in `WebImageService` with a small TTL (e.g., 30 seconds).  
  - Reuse sidecar cache semantics from CR 001-001 to allow `analyze_and_caption` to satisfy requests from sidecars when appropriate.  
  - Extend the analyze endpoint to accept a `force_refresh` flag (query parameter) and pass it through to `WebImageService`.  
  - Use `asyncio.gather` in web service methods to perform independent Dropbox operations concurrently where safe.

### 4.2 Components & Responsibilities

- `publisher_v2.web.service.WebImageService` — Primary implementation point:  
  - Maintains an in-memory structure like `self._image_cache: tuple[list[str], float] | None` storing image names and expiry timestamp, plus minimal locking via asyncio primitives if needed.  
  - `get_random_image`:
    - Uses the cache when valid; on expiry/miss, refreshes via `DropboxStorage.list_images`.  
    - Uses `asyncio.gather` to download the sidecar (if any) and, where necessary, download the image for SHA256 in parallel.  
  - `analyze_and_caption`:
    - Accepts `force_refresh: bool = False`.  
    - On non-force calls, tries sidecar-based reconstruction (via `parse_sidecar_text` and CR 001-001 semantics) before falling back to OpenAI.  
    - On force calls, skips cache and runs the full AI pipeline, then overwrites the sidecar.  
- `publisher_v2.web.app` — HTTP layer:  
  - Updates `/api/images/{filename}/analyze` to parse `force_refresh` from a query parameter and forward it to the service method.  
- `publisher_v2.web.sidecar_parser` — Already the canonical reader; used as-is for sidecar-first behavior; any higher-level cache semantics come from CR 001-001 helpers.  

### 4.3 Data & Contracts

- HTTP contracts:
  - No changes to response schemas for `/api/images/random` or `/api/images/{filename}/analyze`.  
  - New optional query parameter on analyze endpoint:
    - `force_refresh: bool` (e.g., `?force_refresh=true`); defaults to `false` when absent.  
- Sidecars:
  - Same format and fields as defined in Feature 001.  
  - On a force-refresh analyze call, sidecar contents (sd_caption + metadata) are regenerated and overwrite the previous sidecar via `write_sidecar_text`.  
- Internal state:
  - Image-list cache stores only filenames (and possibly hashes returned by `list_images_with_hashes` in future features); no AI outputs are cached in memory.

### 4.4 Error Handling & Edge Cases

- Image list cache:
  - On Dropbox errors during refresh, cache is not updated; the error propagates as a normal 5xx, matching existing behavior.  
  - Stale cache entries may reference images removed from Dropbox; in that case, downstream Dropbox calls will raise `StorageError`/`FileNotFoundError`, which are already handled at the web layer. On error, the cache should be invalidated on the next request.  
- Sidecar cache:
  - If sidecar parse fails or sidecar-derived data is incomplete, the service falls back to fresh analysis/caption.  
  - Logs should clearly indicate when a sidecar cache hit was attempted, and whether it was used or discarded due to parse/validation issues.  
- Parallel Dropbox calls:
  - Exceptions raised by any `asyncio.gather` task must be caught and translated into existing error responses; parallelization must not leak raw exceptions.  
  - Partial failures (e.g., temp link OK but sidecar download fails) should behave as before: sidecar treated as missing, request still succeeds if other parts are OK.  

### 4.5 Security, Privacy, Compliance

- Auth:
  - No changes to auth middleware or admin controls; cache behavior is only applied after requests have been authenticated/authorized.  
- Data:
  - The in-memory cache holds only filenames and does not introduce new PII or sensitive data storage.  
  - Sidecar reuse does not change the set of data stored in Dropbox; it only reduces repeated reads/writes.  
- Logging:
  - New log fields must not include secrets or full SD captions; use boolean flags and filenames only.  

## 5. Detailed Flow

- Main success path: `GET /api/images/random` (with cache):
  1. FastAPI handler calls `WebImageService.get_random_image()`.  
  2. Service checks image-list cache:
     - If cache is valid (not expired), reuses the cached list.  
     - If expired or empty, calls `DropboxStorage.list_images`, stores the list with a new expiry timestamp, and logs `image_list_cache_refresh`.  
  3. Service selects a random image from the list.  
  4. Using `asyncio.gather`, service concurrently:
     - Requests a temporary link via `get_temporary_link`.  
     - Attempts to download and parse the sidecar (for caption/sd_caption/metadata).  
     - Optionally downloads the image bytes for SHA256 (if hash display remains desired).  
  5. Service composes `ImageResponse` exactly as today and returns it.  

- Main success path: `POST /api/images/{filename}/analyze` (sidecar-first):
  1. Handler parses query parameter `force_refresh` (default `false`) and calls `WebImageService.analyze_and_caption(filename, correlation_id, force_refresh)`.  
  2. Service ensures the image exists by requesting a temporary link (as today).  
  3. If `force_refresh` is `false`:
     - Service attempts to download and parse the sidecar; if successful and sidecar-derived data passes minimal validity checks, it reconstructs the response (caption, sd_caption, metadata-derived fields) without calling OpenAI.  
     - Logs `web_analyze_sidecar_cache_hit` and returns `AnalysisResponse`.  
  4. If `force_refresh` is `true`, or the sidecar path fails:
     - Service runs the full vision analysis + SD caption pipeline via `AIService` (per CR 001-002 integration).  
     - Writes/overwrites the sidecar and logs start/complete events.  
     - Returns the fresh `AnalysisResponse`.  

- Key edge flows:
  - Cached image list contains filenames that have since been archived or deleted: downstream Dropbox calls fail, request returns 404/500 as before; cache is effectively “self-healing” on subsequent refreshes.  
  - Sidecar present but missing metadata block: service uses `sd_caption` alone, treating it as a cache hit for caption fields while leaving metadata fields empty.  

## 6. Testing Strategy (for this Change)

- Unit tests:
  - `web/test_web_service.py`:
    - Tests for `get_random_image` verifying that:
      - First call populates cache; subsequent calls within TTL reuse it and do not re-invoke `list_images`.  
      - Cache expiry triggers a refresh.  
    - Tests for `analyze_and_caption` verifying:
      - Sidecar cache hit path (no AI calls when valid sidecar exists and `force_refresh=False`).  
      - Sidecar parse failure or missing sidecar leads to AI calls and sidecar rewrite.  
      - `force_refresh=True` bypasses cache and re-runs AI even when sidecar exists.  
  - `web/test_sidecar_parser.py` / helpers: ensure parser remains backward compatible for all supported sidecar formats used in cache logic.  
- Integration tests:
  - `web_integration/test_web_endpoints.py`:
    - Extend tests for `/api/images/random` to use mocks and confirm only one `list_images` call across multiple requests within TTL.  
    - Extend tests for `/api/images/{filename}/analyze` to cover:
      - Sidecar-first behavior when sidecar exists.  
      - `?force_refresh=true` forcing a new AI run and sidecar overwrite.  
- E2E / manual:
  - Deploy to staging and manually exercise “Next Image” and “Analyze & Caption” repeat flows, observing latency improvements and verifying no regressions in behavior or UI.

## 7. Risks & Alternatives

- Risks:
  - Incorrect cache invalidation could cause confusing behavior (e.g., images not appearing/disappearing promptly) — mitigated by using a small TTL and not caching metadata about contents beyond filenames.  
  - Sidecar-first behavior could hide underlying AI or sidecar-writing bugs — mitigated by logging cache hits and allowing explicit force-refresh paths.  
  - Parallel Dropbox calls might complicate debugging — mitigated by structured logging for each sub-call and thorough tests.  
- Alternatives:
  - Per-request caching via HTTP or CDN — rejected because content is private and latency is dominated by backend calls, not HTTP transfer.  
  - Adding a persistent metadata index for images — rejected as out of scope (would require a new database).  

## 8. Work Plan (Scoped)

- Implement an in-memory image list cache in `WebImageService.get_random_image` with a modest TTL (e.g., 30s).  
- Update `WebImageService.get_random_image` and `analyze_and_caption` to use `asyncio.gather` for independent Dropbox operations.  
- Extend `WebImageService.analyze_and_caption` and the corresponding FastAPI route to support a `force_refresh` query parameter and to reuse sidecars as a cache when appropriate.  
- Add or update unit and integration tests in `publisher_v2/tests/web` and `publisher_v2/tests/web_integration` to cover cache and parallelization behaviors.  
- Verify via tests and manual checks that HTTP contracts, auth semantics, and sidecar behavior remain backward compatible.

## 9. Open Questions

- What default TTL should be used for the image list cache (30s vs. 60s), and should it be configurable via INI or environment variables? — Proposed answer: start with a 30s constant and only promote to config if needed.  
- Should the API explicitly indicate when results came from cache (e.g., a `cache_hit` field)? — Proposed answer: keep this out of the public API for now; use logs only.  
- Should we avoid computing SHA256 entirely in the web UI (relying solely on Dropbox content hashes)? — Proposed answer: potentially a follow-up optimization; this change focuses on caching and sidecar reuse.

