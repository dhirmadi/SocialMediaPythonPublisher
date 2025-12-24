# Story Summary: Backend Support for Review Mode

**Feature ID:** 019
**Story ID:** 019-02
**Status:** Shipped
**Date Completed:** 2025-12-06

## Summary
Implemented the backend API foundation for Review Mode.
- Refactored `WebImageService` to use a shared `_build_image_response` method, eliminating duplication between random and specific image fetching.
- Added `GET /api/images/list` endpoint which returns a sorted list of image filenames, using the same filtering logic as the random selector.
- Added `GET /api/images/{filename}` endpoint to fetch details for a specific image.
- Ensured proper route ordering in `app.py` so `/list` is not captured by `/{filename}`.
- Added unit tests verifying the new endpoints and route precedence.

## Files Changed
### Source Files
- `publisher_v2/src/publisher_v2/web/models.py` — Added `ImageListResponse` model.
- `publisher_v2/src/publisher_v2/web/service.py` — Refactored `get_random_image`, added `list_images` and `get_image_details`, extracted `_build_image_response`.
- `publisher_v2/src/publisher_v2/web/app.py` — Added `/api/images/list` and `/api/images/{filename}` routes.

### Test Files
- `publisher_v2/tests/web/test_web_endpoints.py` — New tests for list, specific image, and routing.

### Documentation
- `docs_v2/08_Epics/002_web_admin_curation_ux/019_swipe_workflow_modes/stories/02_review_mode_backend/019_02_design.md`
- `docs_v2/08_Epics/002_web_admin_curation_ux/019_swipe_workflow_modes/stories/02_review_mode_backend/019_02_plan.yaml`

## Test Results
- Tests: 4 passed
- Coverage: N/A (Unit tests cover new logic)

## Acceptance Criteria Status
- [x] AC1: GET /api/images/list returns sorted list
- [x] AC2: GET /api/images/{filename} returns ImageResponse
- [x] AC3: Refactored GET /api/images/random works
- [x] AC4: Route ordering is correct
- [x] AC5: List is cached (via `_get_cached_images`)

## Follow-up Items
- None.

