<!-- docs_v2/08_Features/08_04_ChangeRequests/001/003_sidecar-not-found-fast-path_design.md -->

# Sidecar Not-Found Fast Path — Change Design

**Feature ID:** 001  
**Change ID:** 001-003  
**Parent Feature:** Stable Diffusion Caption File  
**Design Version:** 1.0  
**Date:** 2025-11-20  
**Status:** Design Review  
**Author:** Architecture Team  
**Linked Change Request:** docs_v2/08_Features/08_04_ChangeRequests/001/003_sidecar-not-found-fast-path.md  
**Parent Feature Design:** docs_v2/08_Features/08_02_Feature_Design/001_captionfile_design.md  

## 1. Summary

- **Problem & context:** The Stable Diffusion caption file feature (001) and its sidecar-as-cache changes (001-001, 001-002) assume sidecars are cheap to read, but the current implementation uses the generic `DropboxStorage.download_image` path with tenacity retries. When a sidecar `.txt` is missing, Dropbox returns a "not found" error that is retried multiple times, adding seconds to key web endpoints (`/api/images/random`, `/api/images/{filename}/analyze`) even though the "no sidecar yet" state is normal.  
- **Goal of this change:** Introduce a dedicated, sidecar-aware read helper that treats "not found" as an expected, fast-path outcome while preserving robust behavior for genuine transient errors, and wire the web service to use it.  
- **Non-goals:** Do not alter sidecar creation, format, or archival semantics defined by Feature 001; do not change AI behavior, prompts, or SD caption generation logic.

## 2. Context & Assumptions

- **Current behavior (affected parts):**
  - Feature 001 design defines `DropboxStorage.write_sidecar_text` and describes moving `.txt` sidecars alongside images during archive; reading sidecars is handled by callers (e.g., `WebImageService`) using the generic `download_image` API.
  - `WebImageService.get_random_image` currently uses `asyncio.gather` to call `DropboxStorage.get_temporary_link`, `DropboxStorage.download_image(folder, sidecar_name)`, and `DropboxStorage.download_image(folder, selected)` in parallel, with `return_exceptions=True`. Sidecar parsing is conditional on `sidecar_result` not being an exception.
  - `WebImageService.analyze_and_caption` ensures the image exists via `get_temporary_link`, then, when not forcing refresh, attempts to read an existing sidecar by calling `download_image` for `image.txt` wrapped in a broad `try/except Exception`, treating any exception as "no sidecar".
  - `DropboxStorage.download_image` is decorated with tenacity `@retry(stop_after_attempt(3), wait=wait_exponential(min=1,max=8))`, designed for transient network/API issues when downloading primary image bytes.
- **Constraints from parent feature & sidecar-cache CRs:**
  - Sidecars remain optional add-ons; absence of a `.txt` file must never be treated as an error condition for callers.
  - Sidecar contents and movement semantics (write beside the image, move with archive) must not change.
  - No new persistent stores; Dropbox remains the source of truth.
  - Web flows must remain backward compatible in terms of HTTP contracts and overall behavior, only improving latency.
- **Dependencies:**
  - `publisher_v2.services.storage.DropboxStorage` (Dropbox SDK, tenacity).
  - `publisher_v2.web.service.WebImageService` (web flows that read sidecars).
  - `publisher_v2.web.sidecar_parser` (unchanged; continues to parse sidecar text).

## 3. Requirements

### 3.1 Functional Requirements

- **CR1:** Provide a dedicated, sidecar-aware read helper in `DropboxStorage` (e.g., `async def download_sidecar_if_exists(folder: str, filename: str) -> bytes | None`) that:
  - Derives the `.txt` sidecar path from the given image filename.
  - Returns the raw bytes of the sidecar when present.
  - Returns `None` when Dropbox reports "file not found" for the sidecar, without multiple retry attempts.
- **CR2:** Ensure that transient Dropbox errors (network, throttling, etc.) for sidecar reads continue to be retried according to a tenacity policy, and that persistent non-404 failures surface as exceptions to callers (which may choose to treat them as "no sidecar" for UX).
- **CR3:** Update `WebImageService.get_random_image` and `WebImageService.analyze_and_caption` to use the new sidecar helper for `.txt` reads, preserving all existing caching, parsing, and logging semantics while removing multi-second delays when sidecars are absent.
- **CR4:** Maintain current behavior for image downloads (`download_image`) and sidecar writing/archival (`write_sidecar_text`, `archive_image`); only sidecar-reading behavior is adjusted.

### 3.2 Non-Functional Requirements

- **Performance:** For images without sidecars, sidecar-check latency must be reduced from multi-second retry sequences to a single Dropbox round-trip, making `/api/images/random` and `/api/images/{filename}/analyze` noticeably faster when sidecars are missing.
- **Reliability:** Robust error handling for genuine Dropbox issues must be preserved; the new helper must not mask systemic failures as cache misses without emitting logs where appropriate.
- **Security & Privacy:** No new secrets, scopes, or sensitive data flows; sidecar contents and logging behavior remain governed by Feature 001 and its cache CRs.
- **Observability:** Existing logs (e.g., `web_analyze_sidecar_cache_hit`) remain valid; additional logging for sidecar read failures, if added, must use structured `log_json` and avoid leaking sensitive information.

## 4. Architecture & Design (Delta)

### 4.1 Current vs. Proposed

- **Current:**
  - Sidecar reads in web flows use `DropboxStorage.download_image` directly for `image.txt`. This path is optimized for primary image bytes and includes tenacity retries for any `ApiError`, including 404-style "not found", causing multiple attempts and backoff delays when sidecars do not exist.
  - Web code compensates by catching broad exceptions and treating them as "no sidecar", but cannot avoid the time spent in retries.
- **Proposed:**
  - Introduce `DropboxStorage.download_sidecar_if_exists` as a sidecar-specific helper that:
    - Still uses the Dropbox SDK under the hood.
    - Recognizes Dropbox "not found" errors and treats them as an expected, non-retriable outcome, returning `None` quickly.
    - Optionally leverages tenacity `retry` with a custom predicate so that only retryable errors are re-attempted.
  - Refactor `WebImageService` to call `download_sidecar_if_exists` from both `get_random_image` and `analyze_and_caption`, while leaving other behavior (e.g., `asyncio.gather`, `return_exceptions=True`, sidecar parsing, and cache-hit logging) intact.

### 4.2 Components & Responsibilities

- **`publisher_v2.services.storage.DropboxStorage`**
  - **New helper:** `async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None`  
    - Responsibility: Fast, sidecar-aware read that normalizes "not found" to `None` and allows callers to distinguish between "no sidecar" and other failures.
  - **New internal helper:** `_is_sidecar_not_found_error(exc: ApiError) -> bool`  
    - Responsibility: Inspect Dropbox `ApiError` to identify "file not found" conditions for sidecar paths.
- **`publisher_v2.web.service.WebImageService`**
  - **`get_random_image`**  
    - Responsibility change: Use `download_sidecar_if_exists` instead of `download_image` for `.txt` reads in the `asyncio.gather` call; treat `None` as "no sidecar" and continue to prefer sidecar-derived caption/metadata when present.
  - **`analyze_and_caption`**  
    - Responsibility change: Replace the `try/except` + `download_image` pattern with a single call to `download_sidecar_if_exists`, falling back to AI analysis when the helper returns `None`.
- **Tests**
  - **`publisher_v2/tests/test_dropbox_sidecar.py`**  
    - Extended to cover `download_sidecar_if_exists` behavior for existing vs. missing sidecars.
  - **`publisher_v2/tests/web/test_web_service.py`**  
    - Extended to assert that missing sidecars result in no exceptions and that sidecar-backed paths still work as before.

### 4.3 Data & Contracts

- **Data:**
  - No changes to sidecar file naming (`image.jpg` → `image.txt`), contents, or archive behavior.
  - No new fields added to sidecar metadata or in-memory models.
- **Contracts:**
  - `DropboxStorage` gains a new, internal-facing API (`download_sidecar_if_exists`) used by the web service; this is additive and does not alter existing public contracts.
  - Web API contracts (`/api/images/random`, `/api/images/{filename}/analyze`) remain unchanged: response shapes, status codes, and semantics are preserved.

### 4.4 Error Handling & Edge Cases

- **Dropbox "file not found" for sidecar:**
  - Detected by `_is_sidecar_not_found_error` in `DropboxStorage`.
  - `download_sidecar_if_exists` returns `None` without raising, allowing callers to treat this as a normal cache miss.
- **Other Dropbox errors (auth, throttling, network):**
  - For the sidecar helper, these are still subject to tenacity retry (if configured) and ultimately surface as exceptions.
  - In `get_random_image`, such exceptions will appear in the `asyncio.gather` result and be ignored for sidecar parsing, maintaining current "best effort" behavior.
  - In `analyze_and_caption`, they may either be caught and treated as "no sidecar" (maintaining today’s semantics) or allowed to bubble as 5xx; we prefer to preserve current practice of not failing the endpoint due solely to sidecar-read issues.
- **Invalid sidecar contents:**
  - Parsing remains handled by `rehydrate_sidecar_view`; invalid or partial sidecars fall back to AI analysis exactly as defined in CR 001-001.

### 4.5 Security, Privacy, Compliance

- No changes to auth, access rules, or credentials.
- Sidecar contents remain governed by Feature 001 (PG-13 SD captions, no PII, no new sensitive fields).
- Logging must not include raw sidecar contents; any new logs should only report high-level outcomes (e.g., "sidecar_not_found", "sidecar_read_error") with sanitized error messages.

## 5. Detailed Flow

### 5.1 `download_sidecar_if_exists` Flow

1. Caller passes `folder` and image `filename` (e.g., `"image.jpg"`).
2. Helper computes `sidecar_name = f"{stem}.txt"` using `os.path.splitext`.
3. It attempts a Dropbox `files_download` for the sidecar path in a thread via `asyncio.to_thread`.
4. If the call succeeds, the sidecar bytes are returned.
5. If Dropbox raises an `ApiError`:
   - If `_is_sidecar_not_found_error(exc)` is `True`, the helper returns `None` immediately.
   - Otherwise, the error is either retried (tenacity) or ultimately raised as a `StorageError`, depending on the configured retry policy.

### 5.2 `get_random_image` Flow (Delta)

1. `_get_cached_images` returns the cached or freshly listed candidate filenames.
2. A random image `selected` is chosen.
3. `asyncio.gather` is invoked with:
   - `get_temporary_link(folder, selected)`
   - `download_sidecar_if_exists(folder, selected)`
   - `download_image(folder, selected)` for the image bytes
4. After gather:
   - If the temp link call failed, an exception is raised as before.
   - If `sidecar_result` is a non-exception and not `None`, it is decoded and parsed via `rehydrate_sidecar_view` to populate `sd_caption`, `caption`, `metadata`, and `has_sidecar`.
   - If `sidecar_result` is `None` or an exception, the image is treated as having no sidecar.
   - SHA256 is optionally computed from `image_result` as today.

### 5.3 `analyze_and_caption` Flow (Delta)

1. `get_temporary_link` validates that the image exists.
2. If `force_refresh` is `False`:
   - `download_sidecar_if_exists(folder, filename)` is called.
   - If bytes are returned and sidecar parsing yields a usable caption and/or `sd_caption`, the method returns an `AnalysisResponse` constructed from the sidecar view and logs a `web_analyze_sidecar_cache_hit`.
   - If the helper returns `None` or any error is treated as "no sidecar", the flow falls through to AI analysis.
3. If `force_refresh` is `True` or no usable sidecar is found:
   - AI analysis + caption/SD-caption generation proceeds as defined in CR 001-001 and 001-002.
   - On success, a sidecar is (re)written via `write_sidecar_text`, unchanged.

## 6. Testing Strategy (for this Change)

- **Unit tests:**
  - Extend `test_dropbox_sidecar.py` to cover:
    - Successful sidecar download via `download_sidecar_if_exists`.
    - "File not found" behavior resulting in `None` and no exception.
    - Optional: behavior when an `ApiError` that is not "not found" is raised (e.g., ensure it bubbles or is wrapped appropriately).
- **Web service tests:**
  - Extend `tests/web/test_web_service.py` to ensure:
    - `get_random_image` continues to populate sidecar-derived fields correctly when a sidecar exists, using the new helper.
    - `get_random_image` behaves correctly when sidecars are missing, with no unexpected exceptions.
    - `analyze_and_caption` still prefers sidecar cache when available, and falls back to AI when sidecars are missing.
- **Integration/E2E (optional for this change):**
  - Leverage existing web endpoint tests to validate that behavior and responses remain unchanged; focus on ensuring no new errors occur when sidecars are absent.

## 7. Risks & Alternatives

- **Risks:**
  - **Incorrect "not found" detection:** If `_is_sidecar_not_found_error` misclassifies errors, the helper might treat real issues as cache misses. Mitigation: Implement targeted tests with simulated Dropbox error objects and keep classification logic narrow.
  - **Divergent semantics between sidecar and image downloads:** Introducing a specialized helper could confuse future contributors. Mitigation: Clearly document the helper’s purpose and ensure all sidecar reads converge on it.
- **Alternatives Considered:**
  - **Adjusting tenacity on `download_image` globally:** Rejected; would affect all image downloads, not just sidecars, and risks under-retrying genuine image download failures.
  - **Using only metadata (`files_get_metadata`) to check for sidecar existence:** Considered as a future optimization; for this change, a single, non-retriable download attempt for missing sidecars is sufficient and simpler to reason about.

## 8. Work Plan (Scoped)

- **Task 1:** Implement `DropboxStorage.download_sidecar_if_exists` and `_is_sidecar_not_found_error`, including any tenacity retry predicate if used.
- **Task 2:** Refactor `WebImageService.get_random_image` to use the new helper in its `asyncio.gather` call for sidecar reads.
- **Task 3:** Refactor `WebImageService.analyze_and_caption` to use the new helper instead of the generic `download_image` + `try/except` pattern for cache-first logic.
- **Task 4:** Extend `test_dropbox_sidecar.py` with unit tests for the new helper and its error classification behavior.
- **Task 5:** Extend `tests/web/test_web_service.py` to validate sidecar-present and sidecar-absent behavior under the new helper, ensuring no regressions in existing web flows.

## 9. Open Questions

- Should `download_sidecar_if_exists` be the only supported API for sidecar reads going forward (e.g., should other components be refactored to use it), or is it acceptable to scope its usage to the web layer for now? — Proposed answer: Scope initially to web flows, then refactor other sidecar consumers to use it in follow-up work if needed.
- Do we need additional structured logging around sidecar read failures (e.g., `sidecar_not_found`, `sidecar_read_error`) for observability, or is the existing web telemetry sufficient? — Proposed answer: Start without new log events; add them only if operational debugging shows a need.


