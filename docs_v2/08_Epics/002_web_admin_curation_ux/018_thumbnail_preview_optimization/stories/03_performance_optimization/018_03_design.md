# Story 018-03: Performance Optimization — Design

**Story ID:** 018-03  
**Design Version:** 1.1  
**Date:** 2025-12-06  
**Status:** Partially Implemented (Preloading only)  
**Parent Story:** 018_03_performance_optimization.md  
**Priority:** Optional

## 1. Overview

This story adds advanced performance optimizations to the thumbnail system. These are "nice-to-have" enhancements that improve the curation workflow experience but are not required for core functionality.

## 2. Optimization Strategies

### 2.1 Thumbnail Preloading

**Goal**: Eliminate wait time between images during curation.

**Approach**: While the user views the current image, prefetch the next random image's metadata and thumbnail.

```
Timeline:
┌─────────────────────────────────────────────────────────────┐
│ User views Image A                                          │
│ ┌────────────────────────────────────────────────────────┐  │
│ │ Background: Prefetch Image B metadata + thumbnail       │  │
│ └────────────────────────────────────────────────────────┘  │
├─────────────────────────────────────────────────────────────┤
│ User clicks "Next"                                          │
│ ┌────────────────────────────────────────────────────────┐  │
│ │ Instant: Display Image B from cache                     │  │
│ │ Background: Prefetch Image C metadata + thumbnail       │  │
│ └────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
```

**Implementation:**

```javascript
let prefetchedImage = null;

async function prefetchNextThumbnail() {
  try {
    // Fetch next random image metadata
    const res = await fetch("/api/images/random");
    if (!res.ok) {
      prefetchedImage = null;
      return;
    }
    const data = await res.json();
    prefetchedImage = data;
    
    // Prefetch thumbnail via link element (leverages browser cache)
    const link = document.createElement("link");
    link.rel = "prefetch";
    link.as = "image";
    link.href = data.thumbnail_url;
    document.head.appendChild(link);
    
    // Clean up after 30 seconds (prevent DOM bloat)
    setTimeout(() => link.remove(), 30000);
  } catch (e) {
    console.warn("Prefetch failed:", e);
    prefetchedImage = null;
  }
}

async function apiGetRandom() {
  // Check for prefetched image
  if (prefetchedImage) {
    const data = prefetchedImage;
    prefetchedImage = null;  // Consume the prefetch
    displayImage(data);
    prefetchNextThumbnail();  // Start prefetching next
    return;
  }
  
  // ... existing fetch logic for cold start ...
  
  // After displaying, start prefetch for next
  prefetchNextThumbnail();
}
```

### 2.2 Configurable Thumbnail Size

**Goal**: Allow deployment-specific tuning of thumbnail size.

**Configuration Hierarchy (highest to lowest priority):**
1. Environment variable: `WEB_THUMBNAIL_SIZE`
2. Static config: `service_limits.yaml` → `web.thumbnail.default_size`
3. Code default: `w960h640`

**Static Config Schema Update:**

```yaml
# service_limits.yaml
web:
  image_cache_ttl_seconds: 30
  thumbnail:
    default_size: "w960h640"
    cache_ttl_seconds: 3600
    enabled: true
```

**Service Implementation:**

```python
class WebImageService:
    VALID_THUMBNAIL_SIZES = {"w256h256", "w480h320", "w640h480", "w960h640", "w1024h768"}
    
    def _get_default_thumbnail_size(self) -> str:
        """Get default thumbnail size from env or config."""
        env_size = os.environ.get("WEB_THUMBNAIL_SIZE", "").strip()
        if env_size in self.VALID_THUMBNAIL_SIZES:
            return env_size
        
        try:
            static = get_static_config()
            cfg_size = static.service_limits.web.thumbnail.default_size
            if cfg_size in self.VALID_THUMBNAIL_SIZES:
                return cfg_size
        except (AttributeError, KeyError):
            pass
        
        return "w960h640"  # Fallback default
```

### 2.3 Skeleton Loading

**Goal**: Provide visual feedback during thumbnail load.

**Approach**: Show an animated placeholder that matches the image container dimensions.

**CSS:**

```css
.image-skeleton {
  width: 100%;
  aspect-ratio: 3/2;  /* Common photo aspect ratio */
  background: linear-gradient(
    90deg,
    #1f2937 0%,
    #374151 50%,
    #1f2937 100%
  );
  background-size: 200% 100%;
  animation: skeleton-shimmer 1.5s ease-in-out infinite;
  border-radius: 0.5rem;
}

@keyframes skeleton-shimmer {
  0% { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}

/* Fade in transition for loaded image */
.image-container img {
  opacity: 0;
  transition: opacity 0.3s ease-in;
}

.image-container img.loaded {
  opacity: 1;
}
```

**HTML:**

```html
<div class="image-container">
  <div id="image-skeleton" class="image-skeleton hidden"></div>
  <div id="image-placeholder" class="image-placeholder">...</div>
  <img id="image" class="hidden" alt="No image loaded yet" />
</div>
```

**JavaScript:**

```javascript
const imageSkeleton = document.getElementById("image-skeleton");

function showSkeleton() {
  imageSkeleton.classList.remove("hidden");
  imgEl.classList.add("hidden");
  imgEl.classList.remove("loaded");
  imagePlaceholder.classList.add("hidden");
}

function showImage(thumbnailUrl, fullUrl, altText) {
  // Show skeleton while loading
  showSkeleton();
  
  // Preload image
  const tempImg = new Image();
  tempImg.onload = () => {
    imageSkeleton.classList.add("hidden");
    imgEl.src = thumbnailUrl;
    imgEl.alt = altText || "Image";
    imgEl.classList.remove("hidden");
    // Trigger fade-in
    requestAnimationFrame(() => {
      imgEl.classList.add("loaded");
    });
  };
  tempImg.onerror = () => {
    showImagePlaceholder("Error loading image.");
  };
  tempImg.src = thumbnailUrl;
  
  currentFullUrl = fullUrl;
  // ... rest unchanged
}
```

### 2.4 Adaptive Sizing

**Goal**: Serve appropriately-sized thumbnails based on viewport.

**Breakpoints:**

| Viewport Width | Thumbnail Size | Rationale |
|----------------|----------------|-----------|
| ≤ 480px        | w480h320       | Mobile phones |
| 481px - 768px  | w640h480       | Tablets, small laptops |
| > 768px        | w960h640       | Desktops, large tablets |

**JavaScript:**

```javascript
function getOptimalThumbnailSize() {
  const width = window.innerWidth;
  if (width <= 480) return "w480h320";
  if (width <= 768) return "w640h480";
  return "w960h640";
}

// Build thumbnail URL with size parameter
function buildThumbnailUrl(baseUrl) {
  const size = getOptimalThumbnailSize();
  const separator = baseUrl.includes("?") ? "&" : "?";
  return `${baseUrl}${separator}size=${size}`;
}

// In apiGetRandom:
const displayUrl = buildThumbnailUrl(data.thumbnail_url || data.temp_url);
```

## 3. Testing Strategy

### 3.1 Preloading Tests

- **Test**: Prefetch link element created after image display
- **Test**: Prefetched image used on "Next" click
- **Test**: Graceful handling when prefetch fails

### 3.2 Configurable Size Tests

- **Test**: Environment variable overrides config
- **Test**: Config value used when no env var
- **Test**: Invalid sizes fall back to default

### 3.3 Skeleton Loading Tests

- **Test**: Skeleton shown during image load
- **Test**: Skeleton hidden when image loads
- **Test**: Smooth transition animation

### 3.4 Adaptive Sizing Tests

- **Test**: Correct size for mobile viewport
- **Test**: Correct size for tablet viewport
- **Test**: Correct size for desktop viewport

## 4. Performance Metrics

### 4.1 Target Improvements

| Metric | Before Optimization | After Optimization |
|--------|---------------------|-------------------|
| Time to next image | ~500ms (API + thumbnail) | ~50ms (prefetched) |
| Perceived responsiveness | Good | Excellent |
| Bandwidth on mobile | ~50KB (w960h640) | ~20KB (w480h320) |

### 4.2 Monitoring

Add log events for optimization effectiveness:

```json
{
  "event": "web_prefetch_hit",
  "filename": "image.jpg",
  "correlation_id": "abc-123"
}
```

```json
{
  "event": "web_adaptive_size",
  "requested_size": "w480h320",
  "viewport_width": 375,
  "correlation_id": "abc-123"
}
```

## 5. Rollback Plan

Each optimization is independent and can be rolled back separately:

1. **Preloading**: Remove `prefetchNextThumbnail()` and related code
2. **Configurable size**: Revert to hardcoded `w960h640`
3. **Skeleton loading**: Remove CSS and skeleton HTML
4. **Adaptive sizing**: Remove `getOptimalThumbnailSize()` and size parameter

## 6. Implementation Order

1. **Preloading** (highest impact for curation workflow)
2. **Adaptive sizing** (bandwidth savings on mobile)
3. **Skeleton loading** (polish)
4. **Configurable size** (operational flexibility)

Each can be implemented as a separate PR for easier review and rollback.

