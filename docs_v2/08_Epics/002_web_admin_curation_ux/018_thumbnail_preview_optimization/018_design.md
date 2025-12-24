# Feature 018: Thumbnail Preview Optimization — Design Document

**Status:** Shipped  
**Version:** 1.0  
**Created:** December 6, 2025

## 1. Context

The web interface currently serves full-resolution images directly from Dropbox, causing:
- 3-15+ second load times on mobile networks
- Poor curation workflow experience (waiting per image)
- Excessive bandwidth consumption

This design details the technical implementation of thumbnail-based previews using Dropbox's native thumbnail API.

## 2. Design Decisions

### 2.1 Thumbnail Size Selection

**Decision:** Default to `w960h640` (960×640 pixels)

**Rationale:**
- Sufficient quality for preview on tablets and desktop (most monitors are 1080p+)
- ~30-80KB typical file size (100-200× smaller than originals)
- Largest "reasonable" size before diminishing returns
- Fits common aspect ratios well (4:3, 3:2, 16:9)

**Alternative considered:** `w640h480` — smaller but noticeably lower quality on tablets.

### 2.2 Thumbnail Serving Strategy

**Decision:** Serve thumbnails via our own endpoint (`/api/images/{filename}/thumbnail`) rather than Dropbox temporary links.

**Rationale:**
1. **Cache control**: We can set `Cache-Control` headers for browser caching
2. **Future flexibility**: Can swap implementation (server-side resize, CDN) without API change
3. **Rate limit management**: Centralized handling of Dropbox API limits
4. **Authentication**: Thumbnails can respect admin-only viewing when AUTO_VIEW is disabled

**Alternative considered:** Generate Dropbox thumbnail temporary links directly. Rejected because Dropbox doesn't provide granular cache control headers.

### 2.3 Backward Compatibility

**Decision:** `temp_url` remains unchanged; `thumbnail_url` is additive.

**Rationale:**
- Existing integrations (if any) continue to work
- Frontend gracefully degrades if `thumbnail_url` is missing (use `temp_url`)
- No breaking changes to API contract

### 2.4 Skip Full Image Download for Display

**Decision:** Do not download full image bytes in `get_random_image()` when only displaying.

**Current behavior:**
```python
# Downloads 5-20MB just to compute SHA256 hash
image_result = await self.storage.download_image(folder, selected)
sha256 = hashlib.sha256(image_result).hexdigest()
```

**Proposed change:** Make SHA256 computation optional/lazy.

**Rationale:**
- SHA256 is primarily for deduplication during publish, not display
- Downloading full image negates thumbnail performance gains
- Hash can be computed on-demand during analyze/publish

## 3. Component Changes

### 3.1 Storage Layer

**File:** `publisher_v2/services/storage.py`

```python
from dropbox.files import (
    ThumbnailSize,
    ThumbnailFormat,
    ThumbnailMode,
    PathOrLink,
)

class DropboxStorage:
    
    # Existing methods unchanged...
    
    @retry(
        reraise=True,
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
    )
    async def get_thumbnail(
        self,
        folder: str,
        filename: str,
        size: ThumbnailSize = ThumbnailSize.w960h640,
        format: ThumbnailFormat = ThumbnailFormat.jpeg,
    ) -> bytes:
        """
        Return a thumbnail of the specified image.
        
        Uses Dropbox's server-side thumbnail generation, which is fast and
        avoids downloading the full image. Default size (960×640) produces
        ~30-80KB files suitable for web preview.
        
        Args:
            folder: Dropbox folder path
            filename: Image filename
            size: Thumbnail size enum (default w960h640)
            format: Output format (default JPEG for smaller files)
        
        Returns:
            Thumbnail image bytes
        
        Raises:
            StorageError: If thumbnail generation fails
        """
        try:
            def _get_thumb() -> bytes:
                path = os.path.join(folder, filename)
                _, response = self.client.files_get_thumbnail_v2(
                    resource=PathOrLink.path(path),
                    size=size,
                    format=format,
                    mode=ThumbnailMode.fitone_bestfit,
                )
                return response.content
            
            return await asyncio.to_thread(_get_thumb)
        except ApiError as exc:
            raise StorageError(f"Failed to get thumbnail for {filename}: {exc}") from exc
```

### 3.2 Web Models

**File:** `publisher_v2/web/models.py`

```python
class ImageResponse(BaseModel):
    filename: str
    temp_url: str                          # Full-size direct link
    thumbnail_url: Optional[str] = None    # NEW: Thumbnail endpoint URL
    sha256: Optional[str] = None
    caption: Optional[str] = None
    sd_caption: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    has_sidecar: bool
```

### 3.3 Web Service

**File:** `publisher_v2/web/service.py`

```python
import urllib.parse

class WebImageService:
    
    async def get_random_image(self) -> ImageResponse:
        images = await self._get_cached_images()
        if not images:
            raise FileNotFoundError("No images found")
        
        import random
        random.shuffle(images)
        selected = images[0]
        folder = self.config.dropbox.image_folder
        
        # CHANGED: Only fetch temp_link and sidecar in parallel
        # Skip full image download for display (performance optimization)
        temp_link_result, sidecar_result = await asyncio.gather(
            self.storage.get_temporary_link(folder, selected),
            self.storage.download_sidecar_if_exists(folder, selected),
            return_exceptions=True,
        )
        
        if isinstance(temp_link_result, Exception):
            raise temp_link_result
        temp_link = temp_link_result
        
        # Parse sidecar (unchanged)
        caption = None
        sd_caption = None
        metadata: Optional[Dict[str, Any]] = None
        has_sidecar = False
        
        if not isinstance(sidecar_result, Exception) and sidecar_result:
            text = sidecar_result.decode("utf-8", errors="ignore")
            view = rehydrate_sidecar_view(text)
            sd_caption = view.get("sd_caption")
            caption = view.get("caption")
            metadata = view.get("metadata")
            has_sidecar = bool(view.get("has_sidecar"))
        
        # NEW: Build thumbnail URL (URL-encode filename for safety)
        thumbnail_url = f"/api/images/{urllib.parse.quote(selected, safe='')}/thumbnail"
        
        return ImageResponse(
            filename=selected,
            temp_url=temp_link,
            thumbnail_url=thumbnail_url,  # NEW
            sha256=None,  # CHANGED: No longer computed during display
            caption=caption,
            sd_caption=sd_caption,
            metadata=metadata,
            has_sidecar=has_sidecar,
        )
    
    async def get_thumbnail(
        self,
        filename: str,
        size: str = "w960h640",
    ) -> bytes:
        """
        Return thumbnail bytes for the specified image.
        
        Args:
            filename: Image filename
            size: Thumbnail size string (maps to ThumbnailSize enum)
        
        Returns:
            JPEG thumbnail bytes
        """
        from dropbox.files import ThumbnailSize
        
        size_map = {
            "w256h256": ThumbnailSize.w256h256,
            "w480h320": ThumbnailSize.w480h320,
            "w640h480": ThumbnailSize.w640h480,
            "w960h640": ThumbnailSize.w960h640,
            "w1024h768": ThumbnailSize.w1024h768,
        }
        thumb_size = size_map.get(size, ThumbnailSize.w960h640)
        
        folder = self.config.dropbox.image_folder
        return await self.storage.get_thumbnail(folder, filename, size=thumb_size)
```

### 3.4 Web API Endpoint

**File:** `publisher_v2/web/app.py`

```python
from fastapi.responses import Response

# Add size validation enum
from enum import Enum

class ThumbnailSizeParam(str, Enum):
    w256h256 = "w256h256"
    w480h320 = "w480h320"
    w640h480 = "w640h480"
    w960h640 = "w960h640"
    w1024h768 = "w1024h768"


@app.get(
    "/api/images/{filename}/thumbnail",
    responses={
        200: {"content": {"image/jpeg": {}}},
        404: {"model": ErrorResponse},
    },
)
async def api_get_thumbnail(
    filename: str,
    request: Request,
    response: Response,
    size: ThumbnailSizeParam = ThumbnailSizeParam.w960h640,
    service: WebImageService = Depends(get_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> Response:
    """
    Return a thumbnail of the specified image.
    
    Thumbnails are generated server-side by Dropbox and cached by
    the browser. This provides fast loading for previews while
    full-size images remain accessible via temp_url.
    
    Size options:
    - w256h256: Small icon (256×256)
    - w480h320: Mobile preview (480×320)
    - w640h480: Tablet preview (640×480)
    - w960h640: Desktop preview (960×640, default)
    - w1024h768: High-quality preview (1024×768)
    """
    # Respect AUTO_VIEW semantics (same as random image endpoint)
    features = service.config.features
    if not getattr(features, "auto_view_enabled", False):
        if not is_admin_configured():
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Image viewing requires admin mode but admin is not configured",
            )
        try:
            require_admin(request)
        except HTTPException:
            raise
    
    try:
        thumb_bytes = await service.get_thumbnail(filename, size=size.value)
        
        web_thumbnail_ms = elapsed_ms(telemetry.start_time)
        response.headers["X-Correlation-ID"] = telemetry.correlation_id
        log_json(
            logger,
            logging.INFO,
            "web_thumbnail_served",
            filename=filename,
            size=size.value,
            bytes_served=len(thumb_bytes),
            correlation_id=telemetry.correlation_id,
            web_thumbnail_ms=web_thumbnail_ms,
        )
        
        return Response(
            content=thumb_bytes,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "public, max-age=3600",  # 1 hour browser cache
                "X-Correlation-ID": telemetry.correlation_id,
            },
        )
    except Exception as exc:
        msg = str(exc)
        if "not found" in msg.lower() or "path/not_found" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Image not found",
            )
        
        web_thumbnail_ms = elapsed_ms(telemetry.start_time)
        log_json(
            logger,
            logging.ERROR,
            "web_thumbnail_error",
            filename=filename,
            error=str(exc),
            correlation_id=telemetry.correlation_id,
            web_thumbnail_ms=web_thumbnail_ms,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate thumbnail",
        )
```

### 3.5 Frontend Changes

**File:** `publisher_v2/web/templates/index.html`

Key changes:
1. Display thumbnail by default
2. Add "View Full Size" action
3. Store full URL for on-demand access

```html
<!-- Add download/view button in controls -->
<div class="controls">
  <button id="btn-next">{{ web_ui_text.buttons.next or "Next image" }}</button>
  <!-- NEW: Full size button (visible when image loaded) -->
  <button id="btn-fullsize" class="secondary hidden">
    {{ web_ui_text.buttons.fullsize or "📥 Full Size" }}
  </button>
  <div id="admin-controls" class="controls admin-only hidden">
    <!-- existing admin buttons -->
  </div>
</div>
```

```javascript
// Store references
const btnFullSize = document.getElementById("btn-fullsize");
let currentFullUrl = null;  // Store full-size URL

function showImage(thumbnailUrl, fullUrl, altText) {
  imagePlaceholder.classList.add("hidden");
  imgEl.src = thumbnailUrl;  // Load thumbnail (fast!)
  imgEl.alt = altText || "Image";
  imgEl.classList.remove("hidden");
  
  // Store full URL for download/view action
  currentFullUrl = fullUrl;
  if (btnFullSize) {
    btnFullSize.classList.remove("hidden");
  }
}

function showImagePlaceholder(message) {
  if (imgEl) {
    imgEl.src = "";
    imgEl.classList.add("hidden");
  }
  if (imagePlaceholder) {
    const fallback = TEXT.placeholders?.image_empty || "No image loaded yet.";
    imagePlaceholder.textContent = message || fallback;
    imagePlaceholder.classList.remove("hidden");
  }
  // Hide full-size button when no image
  currentFullUrl = null;
  if (btnFullSize) {
    btnFullSize.classList.add("hidden");
  }
}

async function apiGetRandom() {
  setActivity("Loading random image…");
  disableButtons(true);
  try {
    // ... existing permission checks ...
    
    const res = await fetch("/api/images/random");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.error || "Failed to load image");
    }
    const data = await res.json();
    currentFilename = data.filename;
    
    // CHANGED: Use thumbnail_url for display, temp_url for full-size
    const displayUrl = data.thumbnail_url || data.temp_url;
    showImage(
      displayUrl,
      data.temp_url,  // Full-size URL stored
      data.caption || data.sd_caption || data.filename
    );
    
    setCaption(data.caption || data.sd_caption || "No caption yet.");
    // ... rest unchanged ...
  } catch (e) {
    // ... error handling unchanged ...
  } finally {
    disableButtons(false);
  }
}

// NEW: Full-size button handler
function handleFullSize() {
  if (currentFullUrl) {
    // Open in new tab for download/viewing
    window.open(currentFullUrl, "_blank");
  }
}

function initLayout() {
  btnNext.addEventListener("click", apiGetRandom);
  // NEW: Wire up full-size button
  if (btnFullSize) {
    btnFullSize.addEventListener("click", handleFullSize);
  }
  // ... rest unchanged ...
}
```

## 4. Configuration

### 4.1 Static Config (Optional Enhancement)

**File:** `publisher_v2/config/static/service_limits.yaml`

```yaml
web:
  image_cache_ttl_seconds: 30
  # NEW: Thumbnail configuration
  thumbnail:
    default_size: "w960h640"
    cache_ttl_seconds: 3600
    enabled: true
```

### 4.2 Environment Override (Optional)

```bash
# Override thumbnail size globally
WEB_THUMBNAIL_SIZE=w640h480  # For bandwidth-constrained deployments
```

## 5. Observability

### 5.1 New Log Events

```json
{
  "event": "web_thumbnail_served",
  "filename": "image.jpg",
  "size": "w960h640",
  "bytes_served": 45678,
  "correlation_id": "abc-123",
  "web_thumbnail_ms": 234
}
```

```json
{
  "event": "web_thumbnail_error",
  "filename": "image.jpg",
  "error": "ApiError: path/not_found",
  "correlation_id": "abc-123",
  "web_thumbnail_ms": 89
}
```

### 5.2 Metrics to Track

- `web_thumbnail_ms`: Latency for thumbnail generation
- `bytes_served`: Thumbnail size (should be ~30-80KB)
- `thumbnail_cache_hit_ratio`: Browser cache effectiveness (via access logs)

## 6. Testing Strategy

### 6.1 Unit Tests

```python
# tests/test_storage_thumbnail.py

import pytest
from unittest.mock import MagicMock, patch
from publisher_v2.services.storage import DropboxStorage

@pytest.mark.asyncio
async def test_get_thumbnail_returns_bytes():
    """Thumbnail method returns image bytes."""
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.content = b"\xff\xd8\xff..."  # JPEG magic bytes
    mock_client.files_get_thumbnail_v2.return_value = (None, mock_response)
    
    storage = DropboxStorage(config)
    storage.client = mock_client
    
    result = await storage.get_thumbnail("/folder", "image.jpg")
    
    assert result == b"\xff\xd8\xff..."
    mock_client.files_get_thumbnail_v2.assert_called_once()


@pytest.mark.asyncio
async def test_get_thumbnail_raises_on_not_found():
    """Thumbnail method raises StorageError for missing files."""
    # ... test ApiError handling
```

### 6.2 API Tests

```python
# tests/test_web_thumbnail_endpoint.py

import pytest
from fastapi.testclient import TestClient
from publisher_v2.web.app import app

def test_thumbnail_endpoint_returns_jpeg():
    """Thumbnail endpoint returns image/jpeg content type."""
    # ... mock service, verify response headers
    
def test_thumbnail_endpoint_respects_auto_view():
    """Thumbnail endpoint requires admin when AUTO_VIEW disabled."""
    # ... test 401/503 responses

def test_thumbnail_endpoint_caches():
    """Thumbnail response includes Cache-Control header."""
    # ... verify Cache-Control: public, max-age=3600
```

### 6.3 Manual Testing Checklist

- [ ] Load image on mobile device over cellular (4G) — should be < 1 second
- [ ] Load image on desktop over WiFi — should be < 0.5 seconds
- [ ] Click "Full Size" button — opens original image in new tab
- [ ] Curation workflow (Keep/Remove 10 images) — smooth, no waiting
- [ ] Admin mode required when AUTO_VIEW=false — 401 response for thumbnails

## 7. Migration Path

### 7.1 Rollout Strategy

1. **Feature flag** (optional): Add `FEATURE_THUMBNAILS=true` to enable
2. **Gradual rollout**: Deploy to staging first, measure latency
3. **Full rollout**: Enable for all environments

### 7.2 Rollback Plan

If issues arise:
1. Frontend falls back to `temp_url` when `thumbnail_url` is missing
2. Remove `/api/images/{filename}/thumbnail` endpoint
3. Revert `ImageResponse` model change

No data migration required; change is purely additive.

## 8. Security Considerations

1. **Authentication**: Thumbnail endpoint respects same `AUTO_VIEW` / admin rules as random image
2. **Path traversal**: Filename is URL-encoded; Dropbox SDK validates paths
3. **Rate limiting**: Inherits Dropbox API rate limits (generous for this use case)
4. **No new secrets**: Uses existing Dropbox credentials

## 9. Future Enhancements

### 9.1 Preloading

Preload next image thumbnail during curation:

```javascript
// After displaying current image, prefetch next
const nextImage = await fetch("/api/images/random");
const link = document.createElement("link");
link.rel = "prefetch";
link.href = nextImage.thumbnail_url;
document.head.appendChild(link);
```

### 9.2 Progressive Loading

Show blur-up placeholder while thumbnail loads:

```javascript
// Generate tiny blurhash placeholder
// Display placeholder → fade to thumbnail
```

### 9.3 WebP Support

If Dropbox adds WebP thumbnail support, switch for ~30% size reduction:

```python
format=ThumbnailFormat.webp  # Not yet available
```

### 9.4 Adaptive Size

Detect viewport and serve appropriate size:

```javascript
const size = window.innerWidth <= 480 ? "w480h320" : "w960h640";
fetch(`/api/images/${filename}/thumbnail?size=${size}`);
```

## 10. Dependencies

### 10.1 Dropbox SDK

Current SDK version supports `files_get_thumbnail_v2`. No upgrade needed.

```python
# Verify in requirements
dropbox>=11.0.0  # Confirmed available
```

### 10.2 No New Dependencies

This feature requires no new Python packages or external services.

---

## 11. Derived Stories

This feature is implemented through three stories:

| Story | Name | Priority | Effort | Description |
|-------|------|----------|--------|-------------|
| **018-01** | Core Thumbnail Support | Required | 4-6 hours | MVP implementation: storage method, API endpoint, model changes, frontend display |
| **018-02** | Full-Size Access UX | Required | 2-3 hours | Add "Full Size" button for downloading/viewing original images |
| **018-03** | Performance Optimization | Optional | 4-8 hours | Preloading, adaptive sizing, skeleton loading, configurable sizes |

### Story 01: Core Thumbnail Support (MVP)
- Add `get_thumbnail()` to `DropboxStorage`
- Add `/api/images/{filename}/thumbnail` endpoint
- Update `ImageResponse` model with `thumbnail_url` field
- Update frontend to display thumbnails by default
- Optimize `get_random_image()` (skip full image download)

### Story 02: Full-Size Access UX
- Add "Full Size" button to web UI controls
- Wire button to open `temp_url` in new tab
- Add i18n support for button label

### Story 03: Performance Optimization (Optional)
- Thumbnail preloading during curation
- Configurable thumbnail sizes via env/config
- Skeleton loading placeholder
- Adaptive sizing based on viewport

**Implementation Order:** Stories must be implemented in sequence (01 → 02 → 03).

