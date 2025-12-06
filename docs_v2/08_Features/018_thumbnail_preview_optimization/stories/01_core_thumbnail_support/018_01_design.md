# Story 018-01: Core Thumbnail Support — Design

**Story ID:** 018-01  
**Design Version:** 1.0  
**Date:** 2025-12-06  
**Status:** Proposed  
**Parent Story:** 018_01_core_thumbnail_support.md

## 1. Overview

This story implements the foundational thumbnail infrastructure using Dropbox's `files/get_thumbnail_v2` API. The design focuses on minimal changes that deliver maximum performance improvement.

## 2. Component Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Web Layer                                │
│  ┌────────────────┐    ┌────────────────┐    ┌──────────────┐  │
│  │   app.py       │───▶│   service.py   │───▶│  models.py   │  │
│  │ (new endpoint) │    │ (get_thumbnail)│    │ (thumbnail_  │  │
│  └────────────────┘    └────────────────┘    │  url field)  │  │
│          │                     │             └──────────────┘  │
└──────────│─────────────────────│───────────────────────────────┘
           │                     │
           ▼                     ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Storage Layer                              │
│  ┌────────────────────────────────────────────────────────┐    │
│  │   storage.py                                            │    │
│  │   + get_thumbnail(folder, filename, size, format)       │    │
│  └────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      Dropbox API                                │
│  files_get_thumbnail_v2(resource, size, format, mode)          │
└─────────────────────────────────────────────────────────────────┘
```

## 3. Detailed Changes

### 3.1 Storage Layer (`storage.py`)

**New Method:**

```python
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
    
    Uses Dropbox's server-side thumbnail generation. Default size
    (960×640) produces ~30-80KB files suitable for web preview.
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

**Imports to Add:**

```python
from dropbox.files import (
    ThumbnailSize,
    ThumbnailFormat,
    ThumbnailMode,
    PathOrLink,
)
```

### 3.2 Web Models (`models.py`)

**Updated `ImageResponse`:**

```python
class ImageResponse(BaseModel):
    filename: str
    temp_url: str
    thumbnail_url: Optional[str] = None  # NEW
    sha256: Optional[str] = None
    caption: Optional[str] = None
    sd_caption: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    has_sidecar: bool
```

### 3.3 Web Service (`service.py`)

**New Method:**

```python
async def get_thumbnail(
    self,
    filename: str,
    size: str = "w960h640",
) -> bytes:
    """Return thumbnail bytes for the specified image."""
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

**Modified `get_random_image()`:**

Key changes:
1. Remove `download_image()` call from parallel gather
2. Build `thumbnail_url` from filename
3. Return `sha256=None` (no longer computed during display)

```python
async def get_random_image(self) -> ImageResponse:
    images = await self._get_cached_images()
    if not images:
        raise FileNotFoundError("No images found")
    
    import random
    random.shuffle(images)
    selected = images[0]
    folder = self.config.dropbox.image_folder
    
    # CHANGED: Remove download_image from parallel fetch
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
    
    # NEW: Build thumbnail URL
    import urllib.parse
    thumbnail_url = f"/api/images/{urllib.parse.quote(selected, safe='')}/thumbnail"
    
    return ImageResponse(
        filename=selected,
        temp_url=temp_link,
        thumbnail_url=thumbnail_url,  # NEW
        sha256=None,  # CHANGED: No longer computed
        caption=caption,
        sd_caption=sd_caption,
        metadata=metadata,
        has_sidecar=has_sidecar,
    )
```

### 3.4 Web API (`app.py`)

**New Enum:**

```python
from enum import Enum

class ThumbnailSizeParam(str, Enum):
    w256h256 = "w256h256"
    w480h320 = "w480h320"
    w640h480 = "w640h480"
    w960h640 = "w960h640"
    w1024h768 = "w1024h768"
```

**New Endpoint:**

```python
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
    """Return a thumbnail of the specified image."""
    # Respect AUTO_VIEW semantics
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
                "Cache-Control": "public, max-age=3600",
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

### 3.5 Frontend (`index.html`)

**JavaScript Changes:**

```javascript
// Add variable to store full URL
let currentFullUrl = null;

// Modified showImage function
function showImage(thumbnailUrl, fullUrl, altText) {
  imagePlaceholder.classList.add("hidden");
  imgEl.src = thumbnailUrl;  // Load thumbnail (fast!)
  imgEl.alt = altText || "Image";
  imgEl.classList.remove("hidden");
  
  // Store full URL for future use (Story 02 will add button)
  currentFullUrl = fullUrl;
}

// Modified showImagePlaceholder
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
  currentFullUrl = null;
}

// Modified apiGetRandom
async function apiGetRandom() {
  setActivity("Loading random image…");
  disableButtons(true);
  try {
    const adminReq = TEXT.status?.admin_required || "Admin mode required to view images.";
    if (!isAdmin && !featureConfig.auto_view_enabled) {
      setActivity(adminReq);
      setDetails("");
      showImagePlaceholder(adminReq);
      return;
    }
    const res = await fetch("/api/images/random");
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || err.error || "Failed to load image");
    }
    const data = await res.json();
    currentFilename = data.filename;
    
    // CHANGED: Use thumbnail_url with fallback to temp_url
    const displayUrl = data.thumbnail_url || data.temp_url;
    showImage(
      displayUrl,
      data.temp_url,  // Store full URL
      data.caption || data.sd_caption || data.filename
    );
    
    setCaption(data.caption || data.sd_caption || "No caption yet.");
    const meta = data.metadata ? JSON.stringify(data.metadata, null, 2) : "None";
    setDetails(`<div><strong>File:</strong> ${data.filename}</div><pre><code>${meta}</code></pre>`);
    setActivity("Image loaded.");
  } catch (e) {
    console.error(e);
    currentFilename = null;
    showImagePlaceholder("Error loading image.");
    setCaption(null);
    setDetails("");
    setActivity(e.message || "Error loading image.");
  } finally {
    disableButtons(false);
  }
}
```

## 4. Error Handling

| Error Condition | Handling |
|-----------------|----------|
| Image not found in Dropbox | Return 404, log `web_thumbnail_error` |
| Dropbox API error (transient) | Retry up to 3 times with exponential backoff |
| Dropbox API error (persistent) | Return 500, log `web_thumbnail_error` |
| Invalid size parameter | FastAPI validates enum, returns 422 |
| Admin required (AUTO_VIEW=false) | Return 401/503 per existing pattern |

## 5. Testing Plan

### Unit Tests (`test_storage_thumbnail.py`)

```python
@pytest.mark.asyncio
async def test_get_thumbnail_returns_bytes():
    """get_thumbnail returns JPEG bytes from Dropbox."""
    # Mock files_get_thumbnail_v2 to return fake JPEG
    # Assert return value matches mock content

@pytest.mark.asyncio  
async def test_get_thumbnail_raises_storage_error_on_api_error():
    """get_thumbnail raises StorageError on Dropbox failure."""
    # Mock files_get_thumbnail_v2 to raise ApiError
    # Assert StorageError is raised

@pytest.mark.asyncio
async def test_get_thumbnail_uses_correct_size():
    """get_thumbnail passes correct ThumbnailSize to Dropbox."""
    # Mock and verify size parameter
```

### API Tests (`test_web_thumbnail_endpoint.py`)

```python
def test_thumbnail_endpoint_returns_jpeg():
    """GET /api/images/{filename}/thumbnail returns image/jpeg."""
    # Mock service, call endpoint, verify Content-Type

def test_thumbnail_endpoint_sets_cache_headers():
    """Thumbnail response includes Cache-Control header."""
    # Verify Cache-Control: public, max-age=3600

def test_thumbnail_endpoint_404_not_found():
    """Thumbnail endpoint returns 404 for missing images."""
    # Mock service to raise appropriate error

def test_thumbnail_endpoint_respects_auto_view_disabled():
    """Thumbnail requires admin when AUTO_VIEW=false."""
    # Test 401/503 responses
```

### Integration Tests

```python
def test_random_image_includes_thumbnail_url():
    """GET /api/images/random includes thumbnail_url in response."""
    # Call endpoint, verify thumbnail_url field present

def test_random_image_does_not_include_sha256():
    """GET /api/images/random no longer computes sha256."""
    # Verify sha256 is None (performance optimization)
```

## 6. Rollback Plan

If issues arise:

1. **Frontend**: Already has fallback to `temp_url` when `thumbnail_url` is missing
2. **Backend**: Remove `/api/images/{filename}/thumbnail` endpoint
3. **Model**: `thumbnail_url` is Optional, so old responses still valid
4. **Service**: Revert `get_random_image()` to include `download_image()` if SHA256 needed

No database/storage migration — purely additive changes.

## 7. Observability

### Log Events

**Success:**
```json
{
  "event": "web_thumbnail_served",
  "filename": "photo.jpg",
  "size": "w960h640",
  "bytes_served": 45678,
  "correlation_id": "abc-123",
  "web_thumbnail_ms": 234
}
```

**Error:**
```json
{
  "event": "web_thumbnail_error",
  "filename": "photo.jpg",
  "error": "ApiError: path/not_found",
  "correlation_id": "abc-123",
  "web_thumbnail_ms": 89
}
```

### Metrics to Monitor

- `web_thumbnail_ms` — should be < 500ms p99
- `bytes_served` — should be 30-80KB typically
- Error rate — should be < 1%

