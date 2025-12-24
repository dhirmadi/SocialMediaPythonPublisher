# Feature 018: Thumbnail Preview Optimization

**ID:** 018  
**Name:** thumbnail-preview-optimization  
**Status:** Shipped  
**Version:** 1.0  
**Date:** 2025-12-06  
**Author:** AI Architect

## Executive Summary

Web interface image loading is painfully slow, especially during curation workflows where users need to view many images in quick succession. The root cause is that full-resolution images (often 5-20MB+) are served directly from Dropbox, even when a small preview would suffice. This proposal introduces server-side thumbnail generation using Dropbox's native thumbnail API, dramatically reducing load times while preserving the ability to access full-resolution images when needed.

## Problem Statement

### Current Architecture

```
┌──────────────┐     GET /api/images/random      ┌──────────────┐
│   Browser    │ ──────────────────────────────▶ │  Heroku Dyno │
│  (Mobile/    │                                 │  (FastAPI)   │
│   Desktop)   │ ◀────────────────────────────── │              │
└──────────────┘     { temp_url: "dropbox.com/   └──────────────┘
       │               full-image-5MB.jpg" }            │
       │                                                │
       ▼                                                ▼
┌──────────────┐     Direct download (~5MB)      ┌──────────────┐
│   <img src>  │ ◀──────────────────────────────▶│   Dropbox    │
│              │     Full-res image every time   │   Storage    │
└──────────────┘                                 └──────────────┘
```

### Pain Points

1. **Slow image loading**: Full-resolution images (5-20MB) take 3-15+ seconds to load on mobile networks
2. **Curation bottleneck**: During Keep/Remove curation, waiting multiple seconds per image is unacceptable
3. **Bandwidth waste**: Users only need a preview; 90%+ of downloaded bytes are never viewed at full resolution
4. **Mobile data consumption**: Heavy bandwidth use on cellular networks

### Measured Impact

| Network Type | Full Image (~8MB) | Expected Thumbnail (~50KB) |
|--------------|-------------------|---------------------------|
| 3G (1 Mbps)  | ~64 seconds       | ~0.4 seconds              |
| 4G (10 Mbps) | ~6.4 seconds      | ~0.04 seconds             |
| WiFi (50 Mbps)| ~1.3 seconds     | ~0.01 seconds             |

**Improvement: 100-150× faster loading times**

## Proposed Solution

### Architecture Change

```
┌──────────────┐     GET /api/images/random      ┌──────────────┐
│   Browser    │ ──────────────────────────────▶ │  Heroku Dyno │
│              │                                 │  (FastAPI)   │
│              │ ◀────────────────────────────── │              │
└──────────────┘     { temp_url: "...",          └──────────────┘
       │               thumbnail_url: "..." }          │
       │                                               │
       ▼ (default)                                     ▼
┌──────────────┐     Thumbnail (~50KB)           ┌──────────────┐
│   <img src>  │ ◀──────────────────────────────▶│   Dropbox    │
│              │     via get_thumbnail_v2        │   Thumbnail  │
└──────────────┘                                 │     API      │
       │                                         └──────────────┘
       │ (on "View Full Size" click)
       ▼
┌──────────────┐     Full-res download           ┌──────────────┐
│   Download   │ ◀──────────────────────────────▶│   Dropbox    │
│   or Modal   │     Original file               │   Storage    │
└──────────────┘                                 └──────────────┘
```

### Technical Approach

#### Option A: Dropbox Thumbnail API (Recommended)

**Leverage Dropbox's native `files/get_thumbnail_v2` API:**

```python
# Available thumbnail sizes
ThumbnailSize:
  w32h32, w64h64, w128h128, w256h256,
  w480h320, w640h480, w960h640, w1024h768, w2048h1536
```

**Pros:**
- No additional infrastructure required
- Zero storage overhead (thumbnails generated on-demand by Dropbox)
- Leverages Dropbox's CDN and caching
- Simple implementation (~50 lines of code)
- Reliable quality and consistent format (JPEG or PNG)

**Cons:**
- Limited size options (but sufficient for preview use case)
- Adds ~100-200ms latency for thumbnail generation (first request)
- Dropbox API rate limits apply (but well within limits for curation)

#### Option B: Server-Side Thumbnail with In-Memory Cache

Generate thumbnails on Heroku dyno using Pillow, cache in memory.

**Pros:**
- Full control over thumbnail size/quality
- Can optimize further (WebP format, etc.)

**Cons:**
- Dyno memory constraints (512MB standard)
- Cache lost on dyno restart
- Added CPU load during generation
- Requires downloading full image first (negates some benefit)

#### Option C: External Image CDN (Cloudinary, imgix)

Route images through a third-party image transformation service.

**Pros:**
- Professional-grade optimization
- Global CDN caching
- Advanced features (face detection, auto-crop, WebP)

**Cons:**
- External dependency and cost (~$0.01-0.05 per 1000 transformations)
- Additional configuration complexity
- Potential latency for first request

### Recommendation: Option A (Dropbox Thumbnail API)

Given the constraints (Heroku, existing Dropbox integration, simplicity requirements), Option A provides the best balance of:
- **Minimal implementation effort** (reuses existing Dropbox SDK)
- **No infrastructure changes** (no new services, caches, or storage)
- **Immediate performance gains** (100×+ faster loading)
- **Zero ongoing cost** (included in Dropbox API)

## Detailed Design

### 1. Storage Layer Changes

Add a new method to `DropboxStorage`:

```python
# publisher_v2/services/storage.py

from dropbox.files import ThumbnailSize, ThumbnailFormat, ThumbnailMode

class DropboxStorage:
    
    @retry(...)
    async def get_thumbnail(
        self,
        folder: str,
        filename: str,
        size: ThumbnailSize = ThumbnailSize.w960h640,
        format: ThumbnailFormat = ThumbnailFormat.jpeg,
    ) -> bytes:
        """
        Return a thumbnail of the image using Dropbox's thumbnail API.
        
        Default size w960h640 provides good quality for web preview
        at ~30-80KB per image (vs 5-20MB for originals).
        """
        def _get_thumb() -> bytes:
            path = os.path.join(folder, filename)
            _, response = self.client.files_get_thumbnail_v2(
                resource=dropbox.files.PathOrLink.path(path),
                size=size,
                format=format,
                mode=ThumbnailMode.fitone_bestfit,
            )
            return response.content
        
        return await asyncio.to_thread(_get_thumb)
```

### 2. Web API Changes

Add a new endpoint and modify the random image response:

```python
# publisher_v2/web/app.py

@app.get("/api/images/{filename}/thumbnail")
async def api_get_thumbnail(
    filename: str,
    size: str = "w960h640",
    service: WebImageService = Depends(get_service),
) -> Response:
    """
    Return a thumbnail of the specified image.
    
    Size options: w256h256, w480h320, w640h480, w960h640, w1024h768
    """
    thumb_bytes = await service.get_thumbnail(filename, size)
    return Response(
        content=thumb_bytes,
        media_type="image/jpeg",
        headers={
            "Cache-Control": "public, max-age=3600",  # 1 hour cache
        },
    )
```

Modify `ImageResponse` to include thumbnail URL:

```python
# publisher_v2/web/models.py

class ImageResponse(BaseModel):
    filename: str
    temp_url: str              # Full-size direct link (for download)
    thumbnail_url: str         # Thumbnail endpoint URL (for preview)
    sha256: Optional[str] = None
    caption: Optional[str] = None
    # ... existing fields
```

### 3. Web Service Changes

```python
# publisher_v2/web/service.py

async def get_random_image(self) -> ImageResponse:
    # ... existing selection logic ...
    
    # Parallel fetch: thumbnail link, sidecar, metadata
    temp_link, sidecar_result = await asyncio.gather(
        self.storage.get_temporary_link(folder, selected),
        self.storage.download_sidecar_if_exists(folder, selected),
        return_exceptions=True,
    )
    
    # Build thumbnail URL (served via our API for caching control)
    thumbnail_url = f"/api/images/{urllib.parse.quote(selected)}/thumbnail"
    
    return ImageResponse(
        filename=selected,
        temp_url=temp_link,
        thumbnail_url=thumbnail_url,
        # ... rest unchanged
    )
```

### 4. Frontend Changes

Update `index.html` to:
1. Display thumbnail by default
2. Add "View Full Size" / "Download" button
3. Optional: Progressive enhancement with loading skeleton

```javascript
// index.html changes (simplified)

function showImage(thumbnailUrl, fullUrl, altText) {
  imagePlaceholder.classList.add("hidden");
  imgEl.src = thumbnailUrl;  // Load fast thumbnail first
  imgEl.alt = altText;
  imgEl.dataset.fullUrl = fullUrl;  // Store for full-size access
  imgEl.classList.remove("hidden");
}

// On API response:
showImage(
  data.thumbnail_url,
  data.temp_url,  // Full-size URL stored for later
  data.caption || data.filename
);

// New "View Full Size" button handler:
btnFullSize.addEventListener("click", () => {
  window.open(imgEl.dataset.fullUrl, "_blank");
});
```

### 5. Configuration (Optional)

Add configurable thumbnail size via environment or static config:

```yaml
# service_limits.yaml additions
web:
  thumbnail_size: "w960h640"      # Default preview size
  thumbnail_cache_ttl_seconds: 3600
```

## API Contract Changes

### Modified: `GET /api/images/random`

**Response (additions in bold):**

```json
{
  "filename": "image.jpg",
  "temp_url": "https://dl.dropboxusercontent.com/...",
  "**thumbnail_url**": "/api/images/image.jpg/thumbnail",
  "sha256": "abc123...",
  "caption": "...",
  "has_sidecar": true
}
```

### New: `GET /api/images/{filename}/thumbnail`

**Parameters:**
- `size` (query, optional): Thumbnail size. One of: `w256h256`, `w480h320`, `w640h480`, `w960h640`, `w1024h768`. Default: `w960h640`

**Response:**
- `200 OK`: JPEG image bytes
- `404 Not Found`: Image does not exist
- `500 Internal Server Error`: Dropbox API failure

**Headers:**
- `Content-Type: image/jpeg`
- `Cache-Control: public, max-age=3600`

## UI/UX Changes

### Before
```
┌─────────────────────────────────────┐
│  [Loading... 3-15 seconds]          │
│                                     │
│  ████████████░░░░░░░░░  45%         │
│                                     │
└─────────────────────────────────────┘
```

### After
```
┌─────────────────────────────────────┐
│  ┌─────────────────────────────┐    │
│  │                             │    │
│  │    [Image Preview]          │    │
│  │    (loads in <0.5s)         │    │
│  │                             │    │
│  └─────────────────────────────┘    │
│                                     │
│  [Next] [Analyze] [Keep] [Remove]   │
│                                     │
│  📥 Download Full Size              │
└─────────────────────────────────────┘
```

### Mobile Considerations
- Thumbnail at 960×640 is optimal for most mobile screens
- Smaller thumbnails (640×480) available for very constrained bandwidth
- Full-size download is explicit user action, not automatic

## Performance Budget

| Metric | Before | After | Target |
|--------|--------|-------|--------|
| Image load time (4G) | 3-8 seconds | <0.5 seconds | ✅ |
| Image load time (WiFi) | 1-2 seconds | <0.2 seconds | ✅ |
| Bandwidth per preview | 5-20 MB | 30-80 KB | ✅ |
| Curation rate | ~4 images/min | ~30 images/min | ✅ |

## Implementation Plan

### Phase 1: Core Thumbnail Support (MVP)
1. Add `get_thumbnail()` to `DropboxStorage`
2. Add `/api/images/{filename}/thumbnail` endpoint
3. Modify `ImageResponse` to include `thumbnail_url`
4. Update frontend to use thumbnail by default

**Effort:** ~4-6 hours

### Phase 2: Full-Size Access
1. Add "Download Full Size" button to UI
2. Add loading indicator for full-size images
3. Optional: Modal/lightbox for full-size viewing

**Effort:** ~2-3 hours

### Phase 3: Optimization (Optional)
1. Server-side response caching (if needed)
2. Preloading next image thumbnail
3. Skeleton/blur-up loading UX
4. Configurable thumbnail sizes

**Effort:** ~4-8 hours (optional)

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Dropbox thumbnail API rate limits | Low | Medium | Default rate limits are generous; batch requests if needed |
| Thumbnail quality insufficient | Low | Low | Use w960h640 (largest reasonable size); users can view full-size |
| API latency spikes | Medium | Low | Add timeout handling; graceful fallback to full-size |
| Breaking change for API consumers | Low | Medium | `thumbnail_url` is additive; `temp_url` unchanged |

## Testing Strategy

1. **Unit tests**: `DropboxStorage.get_thumbnail()` with mocked SDK
2. **Integration tests**: `/api/images/{filename}/thumbnail` endpoint
3. **Manual testing**: Mobile device over cellular, verify load time < 1s
4. **Regression**: Ensure full-size images remain accessible

## Alternatives Considered

### Why not client-side image scaling?
The browser must download the full image before scaling. No bandwidth savings.

### Why not pre-generate thumbnails in Dropbox?
Storage overhead (2× files), sync complexity, processing pipeline needed.

### Why not use WebP format?
Dropbox thumbnail API only supports JPEG/PNG. Could add server-side conversion in Phase 3 if needed.

## Success Criteria

1. ✅ Image preview loads in < 1 second on 4G mobile network
2. ✅ Curation workflow (Keep/Remove) allows viewing 20+ images per minute
3. ✅ Full-size image remains accessible via explicit user action
4. ✅ No regression in existing functionality (analyze, publish, etc.)
5. ✅ Mobile bandwidth usage reduced by 90%+

## Dependencies

- Dropbox Python SDK `files_get_thumbnail_v2` (already available in current SDK version)
- No new infrastructure or services required

## Open Questions

1. Should thumbnail size be user-configurable in the UI?
2. Should we preload the next image's thumbnail during curation?
3. Should we add a "low bandwidth mode" toggle for extremely constrained networks?

---

## Derived Stories

This feature is implemented through three stories:

| Story | Name | Priority | Effort |
|-------|------|----------|--------|
| **018-01** | [Core Thumbnail Support](stories/01_core_thumbnail_support/018_01_core_thumbnail_support.md) | Required | 4-6 hours |
| **018-02** | [Full-Size Access UX](stories/02_fullsize_access_ux/018_02_fullsize_access_ux.md) | Required | 2-3 hours |
| **018-03** | [Performance Optimization](stories/03_performance_optimization/018_03_performance_optimization.md) | Optional | 4-8 hours |

---

## Appendix: Dropbox Thumbnail API Reference

```python
# Available sizes (ThumbnailSize enum)
w32h32     # 32×32 - too small
w64h64     # 64×64 - too small
w128h128   # 128×128 - icon only
w256h256   # 256×256 - small preview
w480h320   # 480×320 - mobile preview
w640h480   # 640×480 - tablet preview
w960h640   # 960×640 - recommended default ✅
w1024h768  # 1024×768 - high-quality preview
w2048h1536 # 2048×1536 - near full-size

# Format options
ThumbnailFormat.jpeg  # Smaller files, lossy
ThumbnailFormat.png   # Larger files, lossless

# Mode options
ThumbnailMode.strict         # Exact size, may crop
ThumbnailMode.bestfit        # Fit within bounds
ThumbnailMode.fitone_bestfit # Fit one dimension exactly (recommended)
```

