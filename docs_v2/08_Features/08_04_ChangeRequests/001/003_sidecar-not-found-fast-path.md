# Sidecar Not-Found Fast Path

**Feature ID:** 001  
**Change ID:** 001-003  
**Status:** Shipped  
**Date Completed:** 2025-11-20  
**Code Branch / PR:** TODO  

## Summary
This change introduces a dedicated, sidecar-aware fast path for reading `.txt` SD-caption sidecar files so that missing sidecars no longer trigger multi-second Dropbox retry sequences. Instead of using the generic `download_image` API for sidecars, the web layer now calls a new helper that treats "not found" as an expected cache miss, significantly improving the responsiveness of `/api/images/random` and `/api/images/{filename}/analyze` when many images do not yet have sidecars.

## Goals
- Make checking for the presence of a `.txt` sidecar file fast and non-disruptive, especially when the file does not exist.
- Preserve robust retry behavior for genuine transient Dropbox errors while treating “not found” as an expected, non-retriable outcome.
- Keep sidecar semantics, formats, and archive behavior from Feature 001 unchanged, while improving end-to-end latency for web and future callers.

## Non-Goals
- Changing the on-disk format, contents, or naming of sidecar files defined by Feature 001.
- Modifying SD caption generation prompts, models, or sidecar-writing behavior.
- Introducing new storage systems or altering archival semantics for images or sidecars.
- Redesigning the existing sidecar-as-cache behavior (CR 001-001) beyond how sidecars are fetched.

## User Value
For operators using the web interface, images without sidecars now load much faster because the system no longer spends several seconds retrying a download that will never succeed. Maintainers benefit from clearer separation between primary image downloads and optional sidecar reads, reducing Dropbox load and improving latency while keeping Feature 001’s sidecar semantics fully intact. This better aligns real-world performance with the sidecar-as-cache intent, particularly in workflows that browse or analyze large sets of images where many are newly added.

## Technical Overview
- **Scope of the change:**  
  - Storage layer: `DropboxStorage` gains a sidecar-specific read helper.  
  - Web layer: `WebImageService` switches to the sidecar helper in random-image and analyze flows.  
  - Tests: Dropbox sidecar tests and web service tests extended to cover the new behavior.
- **Core flow delta:**  
  - Before: Sidecar reads used `download_image` with tenacity retries, so missing sidecars incurred multiple attempts with exponential backoff.  
  - After: Sidecar reads use `download_sidecar_if_exists`, which quickly returns `None` for “not found” conditions without retrying, while still retrying genuine transient errors as appropriate.
- **Key components touched:**  
  - `publisher_v2.services.storage.DropboxStorage`: new `_is_sidecar_not_found_error` and `download_sidecar_if_exists`.  
  - `publisher_v2.web.service.WebImageService`: `get_random_image` and `analyze_and_caption` updated to call the new helper.  
  - Tests: `publisher_v2/tests/test_dropbox_sidecar.py`, `publisher_v2/tests/web/test_web_service.py`.
- **Flags / config:**  
  - No new config flags were introduced; behavior is always-on and backward-compatible.
- **Data/state/sidecar updates:**  
  - No changes to sidecar format, naming (`image.jpg` → `image.txt`), or archival behavior; only read-path performance and error handling were refined.

## Implementation Details
- **Key functions/classes added or modified:**
  - `DropboxStorage._is_sidecar_not_found_error(exc: ApiError) -> bool` detects Dropbox “file not found” path errors for sidecars.
  - `async DropboxStorage.download_sidecar_if_exists(folder: str, filename: str) -> bytes | None` computes the `.txt` name, downloads the sidecar, and returns `None` on not-found without treating it as an error.
  - `WebImageService.get_random_image` now uses `download_sidecar_if_exists` in its `asyncio.gather` call instead of `download_image` for `image.txt`.
  - `WebImageService.analyze_and_caption` now calls `download_sidecar_if_exists` in its sidecar-first cache path instead of manually constructing the `.txt` filename and calling `download_image` with a broad `try/except`.
- **Error handling behavior:**
  - When Dropbox reports a path-based “not found” error for a sidecar, `_is_sidecar_not_found_error` returns `True` and `download_sidecar_if_exists` returns `None`, enabling callers to treat the case as an ordinary cache miss.
  - Non-not-found `ApiError` instances remain subject to tenacity retries in the helper and ultimately surface as `StorageError` if they persist; in the web flows, these errors are either ignored for sidecar parsing (in `get_random_image`) or treated as “no sidecar” for UX parity with previous behavior.
- **Performance / reliability considerations:**
  - Missing sidecars no longer trigger multi-attempt retry backoff, cutting several seconds from common web flows that touch unprocessed images.  
  - Transient Dropbox issues continue to be retried and surfaced, preserving robustness for primary image and sidecar reads when they should succeed.
- **Security / privacy notes:**
  - No new secrets or access scopes were introduced; all Dropbox interactions continue to use the existing `DropboxConfig`.  
  - Logging of sidecar behavior remains high-level; no raw sidecar contents are logged.

## Testing
- **Unit tests:**
  - `publisher_v2/tests/test_dropbox_sidecar.py` now verifies:
    - `write_sidecar_text` still writes `image.txt` correctly.
    - `download_sidecar_if_exists` returns bytes when a sidecar is present.
    - `download_sidecar_if_exists` returns `None` when a simulated Dropbox “not found” error occurs.
- **Integration / web service tests:**
  - `publisher_v2/tests/web/test_web_service.py` was updated so the `_DummyStorage` exposes `download_sidecar_if_exists`, and existing tests validate that:
    - `get_random_image` continues to populate sidecar-derived fields when a sidecar is present.
    - `get_random_image` behaves correctly when sidecars are missing (no errors, no regressions in response shape).  
    - `analyze_and_caption` still writes sidecars and returns expected captions/SD captions.
- **E2E / manual checks:**
  - Existing web endpoint tests (`web_integration` suite) continue to pass unchanged, confirming that HTTP contracts and behavior are preserved while latency improves in missing-sidecar scenarios.

## Rollout Notes
- **Feature/change flags:**  
  - No new flags; change is always enabled and safe as a performance improvement.
- **Monitoring / logs:**  
  - Existing web telemetry (`web_random_image_ms`, `web_analyze_ms`) can be used to observe latency improvements; no new log events were added specifically for this change.
- **Backout strategy:**  
  - If needed, revert the helper and web-service call sites to the prior `download_image` behavior via a code rollback; no migrations or config changes are involved.

## Artifacts
- Change Request: docs_v2/08_Features/08_04_ChangeRequests/001/003_sidecar-not-found-fast-path.md  
- Change Design: docs_v2/08_Features/08_04_ChangeRequests/001/003_sidecar-not-found-fast-path_design.md  
- Change Plan: docs_v2/08_Features/08_04_ChangeRequests/001/003_sidecar-not-found-fast-path_plan.yaml  
- Parent Feature Design: docs_v2/08_Features/08_02_Feature_Design/001_captionfile_design.md  
- PR: TODO

## Final Notes
This change keeps the Stable Diffusion caption file feature’s sidecar semantics fully intact while aligning real-world performance with the sidecar-as-cache intent in the web interface. Future follow-ups could add lightweight metrics or log events specific to sidecar read outcomes, or introduce a metadata-only existence check if additional latency reductions are needed for very large folders. The new `download_sidecar_if_exists` helper should be the preferred pattern for sidecar reads in any future CLI preview or batch features that consume sidecars.