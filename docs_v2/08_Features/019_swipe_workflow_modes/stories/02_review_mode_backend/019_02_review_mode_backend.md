# Story: Backend Support for Review Mode

**Feature ID:** 019
**Story ID:** 019-02
**Name:** review_mode_backend
**Status:** Proposed
**Date:** 2025-12-06
**Parent Feature:** 019_swipe_workflow_modes

## Summary
Add backend endpoints required for "Review Mode": listing all images (sorted) and fetching metadata for a specific named image.

## Scope
- Refactor `WebImageService` to extract `_build_image_response(filename)` from `get_random_image` to ensure DRY response building.
- Implement `WebImageService.list_images()` (returns sorted filenames) using `publisher_v2.utils.images` filtering helpers.
- Implement `WebImageService.get_image_details(filename)` reusing `_build_image_response`.
- Add endpoint `GET /api/images/list` with simple TTL caching (e.g. 60s).
- Add endpoint `GET /api/images/{filename}` (distinct from `/random`).

## Out of Scope
- Frontend integration (Story 03).

## Acceptance Criteria
- `GET /api/images/list` returns a JSON object with a sorted list of filenames.
- `GET /api/images/{filename}` returns the `ImageResponse` for that specific file.
- If filename does not exist, `GET /api/images/{filename}` returns 404.
- `GET /api/images/random` and `GET /api/images/{filename}` return identical structures (DRY logic).
- Route ordering is correct: `/random` and `/list` are accessible and not shadowed by `/{filename}`.

## Technical Notes
- **DRY Refactoring:** Create `_build_image_response(filename)` to handle:
  - Checking sidecar existence.
  - Generating temp link (or thumbnail URL logic).
  - Creating `ImageResponse` object.
- **Route Ordering:** In `publisher_v2/web/app.py`, define `/random` and `/list` endpoints **before** `/{filename}`.
- **Filtering:** Use `is_image_file` from utils to filter the list, ensuring consistency with random selection.
- **Caching:** A simple class-level dictionary or variable with a timestamp in `WebImageService` is sufficient for the list cache.
- **Encoding:** Filenames in the URL path must be properly decoded.
