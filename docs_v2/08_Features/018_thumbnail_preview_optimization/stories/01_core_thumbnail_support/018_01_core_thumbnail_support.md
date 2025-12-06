# Story: Core Thumbnail Support (MVP)

**Feature ID:** 018  
**Story ID:** 018-01  
**Name:** core-thumbnail-support  
**Status:** Proposed  
**Date:** 2025-12-06  
**Parent Feature:** 018_thumbnail_preview_optimization

## Summary

Implement the core thumbnail infrastructure using Dropbox's native `files/get_thumbnail_v2` API. This story delivers the minimum viable implementation that provides immediate performance gains: a new storage method, API endpoint, updated response model, and frontend changes to display thumbnails by default.

## Scope

### In Scope
- Add `get_thumbnail()` method to `DropboxStorage` class
- Add `/api/images/{filename}/thumbnail` API endpoint
- Modify `ImageResponse` model to include `thumbnail_url` field
- Update frontend to display thumbnail by default (fallback to `temp_url`)
- Remove full image download from `get_random_image()` (performance optimization)
- Add unit tests for storage and API layers
- Add observability (structured logging for thumbnail requests)

### Out of Scope (Deferred)
- "Download Full Size" button UI (Story 02)
- Lightbox/modal for full-size viewing (Story 02)
- Thumbnail preloading (Story 03)
- Configurable thumbnail sizes via static config (Story 03)
- Skeleton/blur-up loading UX (Story 03)

## Acceptance Criteria

### AC1: Storage Layer
- **Given** a valid image filename in Dropbox
- **When** `DropboxStorage.get_thumbnail(folder, filename)` is called
- **Then** it returns JPEG thumbnail bytes (~30-80KB) using Dropbox's `files_get_thumbnail_v2` API
- **And** uses `ThumbnailSize.w960h640` as the default size
- **And** retries on transient failures (same pattern as existing methods)

### AC2: API Endpoint
- **Given** a valid image filename
- **When** `GET /api/images/{filename}/thumbnail` is called
- **Then** it returns the thumbnail with `Content-Type: image/jpeg`
- **And** includes `Cache-Control: public, max-age=3600` header
- **And** respects AUTO_VIEW/admin authentication rules

### AC3: API Endpoint - Not Found
- **Given** an invalid or non-existent filename
- **When** `GET /api/images/{filename}/thumbnail` is called
- **Then** it returns 404 Not Found

### AC4: Image Response Model
- **Given** the updated `ImageResponse` model
- **When** `GET /api/images/random` is called
- **Then** the response includes `thumbnail_url` field (e.g., `/api/images/photo.jpg/thumbnail`)
- **And** `temp_url` remains unchanged (full-size Dropbox link)
- **And** `sha256` may be null (no longer computed on display)

### AC5: Frontend Display
- **Given** an image is loaded via the web UI
- **When** the API returns both `thumbnail_url` and `temp_url`
- **Then** the UI displays the thumbnail (faster load)
- **And** stores `temp_url` for future full-size access

### AC6: Frontend Fallback
- **Given** an older API response without `thumbnail_url`
- **When** the frontend receives the response
- **Then** it falls back to using `temp_url` for display (backward compatible)

### AC7: Performance
- **Given** a 4G mobile network connection (10 Mbps)
- **When** an image is loaded
- **Then** the thumbnail loads in < 1 second (vs 3-8 seconds for full-size)

### AC8: Observability
- **Given** a thumbnail request
- **When** it completes (success or failure)
- **Then** structured logs are emitted with `web_thumbnail_served` or `web_thumbnail_error` events
- **And** include `filename`, `size`, `bytes_served`, `correlation_id`, `web_thumbnail_ms`

## Technical Notes

### Files to Modify

1. **`publisher_v2/services/storage.py`**
   - Add `get_thumbnail()` async method
   - Import `ThumbnailSize`, `ThumbnailFormat`, `ThumbnailMode`, `PathOrLink` from `dropbox.files`
   - Follow existing retry pattern with `@retry` decorator

2. **`publisher_v2/web/models.py`**
   - Add `thumbnail_url: Optional[str] = None` to `ImageResponse`

3. **`publisher_v2/web/service.py`**
   - Add `get_thumbnail()` method to `WebImageService`
   - Modify `get_random_image()` to:
     - Build `thumbnail_url` from filename
     - Remove `download_image()` call (skip SHA256 computation)
   - Import `urllib.parse` for URL encoding

4. **`publisher_v2/web/app.py`**
   - Add `ThumbnailSizeParam` enum for validation
   - Add `api_get_thumbnail()` endpoint handler
   - Include telemetry, logging, auth checks

5. **`publisher_v2/web/templates/index.html`**
   - Modify `showImage()` to accept both thumbnail and full URLs
   - Modify `apiGetRandom()` to use `thumbnail_url` with fallback
   - Add `currentFullUrl` variable to store full-size URL

### New Tests

1. **`publisher_v2/tests/test_storage_thumbnail.py`**
   - `test_get_thumbnail_returns_bytes()`
   - `test_get_thumbnail_raises_on_not_found()`
   - `test_get_thumbnail_uses_default_size()`

2. **`publisher_v2/tests/test_web_thumbnail_endpoint.py`**
   - `test_thumbnail_endpoint_returns_jpeg()`
   - `test_thumbnail_endpoint_sets_cache_headers()`
   - `test_thumbnail_endpoint_respects_auto_view()`
   - `test_thumbnail_endpoint_404_not_found()`

### Dropbox SDK Reference

```python
from dropbox.files import (
    ThumbnailSize,      # w960h640, etc.
    ThumbnailFormat,    # jpeg, png
    ThumbnailMode,      # fitone_bestfit
    PathOrLink,         # PathOrLink.path(path)
)

# API call
metadata, response = client.files_get_thumbnail_v2(
    resource=PathOrLink.path("/folder/image.jpg"),
    size=ThumbnailSize.w960h640,
    format=ThumbnailFormat.jpeg,
    mode=ThumbnailMode.fitone_bestfit,
)
thumbnail_bytes = response.content
```

## Dependencies

- No external dependencies
- Dropbox SDK already supports `files_get_thumbnail_v2`
- No new Python packages required

## Definition of Done

- [ ] `DropboxStorage.get_thumbnail()` implemented and tested
- [ ] `/api/images/{filename}/thumbnail` endpoint implemented and tested
- [ ] `ImageResponse` model updated with `thumbnail_url` field
- [ ] `WebImageService.get_thumbnail()` implemented
- [ ] `get_random_image()` optimized (no full image download)
- [ ] Frontend displays thumbnail by default with fallback
- [ ] Unit tests pass
- [ ] Structured logging added for thumbnail requests
- [ ] Manual testing: image loads < 1s on 4G
- [ ] Docs updated if API contract changes warrant it

