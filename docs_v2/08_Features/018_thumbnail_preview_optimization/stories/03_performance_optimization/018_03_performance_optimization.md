# Story: Performance Optimization (Optional)

**Feature ID:** 018  
**Story ID:** 018-03  
**Name:** performance-optimization  
**Status:** Proposed  
**Date:** 2025-12-06  
**Parent Feature:** 018_thumbnail_preview_optimization  
**Priority:** Optional / Nice-to-Have

## Summary

Implement advanced performance optimizations for the thumbnail preview system. These enhancements improve the user experience during rapid curation workflows but are not required for the core functionality delivered in Stories 01 and 02.

## Scope

### In Scope
- **Thumbnail preloading**: Prefetch next image thumbnail during current image display
- **Configurable thumbnail sizes**: Allow thumbnail size configuration via static config or environment
- **Skeleton/blur-up loading**: Show loading placeholder while thumbnail loads
- **Adaptive sizing**: Detect viewport and serve appropriately-sized thumbnails

### Out of Scope
- Server-side caching (Heroku dyno constraints make this impractical)
- WebP format support (not available in Dropbox thumbnail API)
- CDN integration (out of scope for this feature)

## Acceptance Criteria

### AC1: Thumbnail Preloading
- **Given** an image is currently displayed
- **When** the user is viewing the image
- **Then** the next random image thumbnail is prefetched in the background
- **And** when "Next" is clicked, the prefetched thumbnail loads instantly

### AC2: Configurable Default Size
- **Given** the static config `service_limits.yaml` has `web.thumbnail.default_size: "w640h480"`
- **When** a thumbnail is requested without explicit size
- **Then** the configured default size is used instead of w960h640

### AC3: Environment Override
- **Given** `WEB_THUMBNAIL_SIZE=w480h320` is set in environment
- **When** a thumbnail is requested
- **Then** the environment value overrides static config

### AC4: Skeleton Loading
- **Given** a thumbnail is being loaded
- **When** the request is in flight
- **Then** a subtle loading skeleton/placeholder is shown
- **And** it transitions smoothly to the thumbnail when loaded

### AC5: Adaptive Sizing
- **Given** the user is on a mobile device with viewport width <= 480px
- **When** a thumbnail is requested
- **Then** the frontend requests `w480h320` size instead of `w960h640`

## Technical Notes

### Preloading Implementation

```javascript
// After displaying current image, prefetch next
async function prefetchNextThumbnail() {
  try {
    const res = await fetch("/api/images/random");
    const data = await res.json();
    
    // Store prefetched data
    prefetchedImage = data;
    
    // Prefetch thumbnail via link element (browser caches it)
    const link = document.createElement("link");
    link.rel = "prefetch";
    link.href = data.thumbnail_url;
    document.head.appendChild(link);
  } catch (e) {
    // Silent fail - prefetch is best-effort
    prefetchedImage = null;
  }
}

// Modified apiGetRandom to use prefetched image
async function apiGetRandom() {
  if (prefetchedImage) {
    const data = prefetchedImage;
    prefetchedImage = null;
    displayImage(data);
    prefetchNextThumbnail();  // Start prefetching next
    return;
  }
  // ... existing fetch logic ...
}
```

### Configurable Size Implementation

**Static Config (`service_limits.yaml`):**
```yaml
web:
  image_cache_ttl_seconds: 30
  thumbnail:
    default_size: "w960h640"
    enabled: true
```

**Service Layer:**
```python
def get_default_thumbnail_size(self) -> str:
    """Get default thumbnail size from config or environment."""
    env_size = os.environ.get("WEB_THUMBNAIL_SIZE")
    if env_size and env_size in self.VALID_SIZES:
        return env_size
    
    static = get_static_config()
    return static.service_limits.web.thumbnail.default_size
```

### Skeleton Loading CSS

```css
.image-skeleton {
  background: linear-gradient(90deg, #1f2937 25%, #374151 50%, #1f2937 75%);
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s infinite;
  border-radius: 0.5rem;
  aspect-ratio: 3/2;  /* Common photo ratio */
}

@keyframes skeleton-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
```

### Adaptive Sizing JavaScript

```javascript
function getOptimalThumbnailSize() {
  const width = window.innerWidth;
  if (width <= 480) return "w480h320";
  if (width <= 768) return "w640h480";
  return "w960h640";
}

// Use in API call
const size = getOptimalThumbnailSize();
const thumbnailUrl = `${data.thumbnail_url}?size=${size}`;
```

## Dependencies

- **Story 01 (Core Thumbnail Support)**: Required - provides base infrastructure
- **Story 02 (Full-Size Access UX)**: Required - ensures users can still access full images

## Sub-Tasks

### 3a: Thumbnail Preloading
- Add `prefetchedImage` variable
- Add `prefetchNextThumbnail()` function  
- Modify `apiGetRandom()` to check for prefetched image
- Call prefetch after displaying image

### 3b: Configurable Default Size
- Update `service_limits.yaml` schema
- Add config reading in `WebImageService`
- Add environment variable override
- Update tests

### 3c: Skeleton Loading
- Add `.image-skeleton` CSS class
- Add skeleton HTML element
- Show skeleton during thumbnail load
- Fade transition to loaded image

### 3d: Adaptive Sizing
- Add `getOptimalThumbnailSize()` function
- Pass size parameter to thumbnail endpoint
- Handle viewport resize (optional)

## Risks and Considerations

### Preloading
- **Risk**: Extra API calls increase Dropbox rate limit usage
- **Mitigation**: Only prefetch one image ahead; rate limits are generous

### Skeleton Loading
- **Risk**: May feel "busy" if thumbnails load too fast
- **Mitigation**: Only show skeleton after 200ms delay; CSS transition handles instant loads

### Adaptive Sizing
- **Risk**: Complexity in managing multiple sizes
- **Mitigation**: Keep simple (3 breakpoints max); default to largest size on error

## Definition of Done

- [ ] Preloading implemented and tested
- [ ] Configurable size via static config and env var
- [ ] Skeleton loading with smooth transition
- [ ] Adaptive sizing based on viewport
- [ ] No increase in perceived latency for fast connections
- [ ] Curation workflow feels instant (< 200ms between images)
- [ ] Manual testing on mobile and desktop

