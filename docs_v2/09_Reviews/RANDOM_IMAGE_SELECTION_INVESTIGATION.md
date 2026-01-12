# Investigation Report: Random Image Selection Perceived Non-Randomness

**Date:** 2026-01-12  
**Status:** Investigation Complete  
**Priority:** Medium  
**Affects:** Web UI random image browsing, CLI publish workflow

---

## Executive Summary

Users report that when browsing ~1000 images via the "random" feature, images that are "close to each other" are selected more often than expected. Investigation reveals this is caused by a combination of:

1. **No history tracking** in the web UI's random selection
2. **Deterministic Dropbox ordering** creating correlated starting lists
3. **Human perception bias** toward clustering in true randomness
4. **Birthday paradox** making repeats statistically expected

The publish workflow has deduplication (won't re-publish the same image), but the web browsing flow has no such protection. This report proposes solutions to improve perceived randomness and add auditability.

---

## Investigation Findings

### 1. Current Implementation Analysis

#### Web UI: `get_random_image()` (`web/service.py:265-276`)

```python
async def get_random_image(self) -> ImageResponse:
    images = await self._get_cached_images()
    if not images:
        raise FileNotFoundError("No images found")

    import random
    random.shuffle(images)
    selected = images[0]
    ...
```

**Issues identified:**

| Issue | Impact | Severity |
|-------|--------|----------|
| No history of previously shown images | Same image can appear in consecutive requests | High |
| Uses Python's `random` module (Mersenne Twister PRNG) | Not cryptographically secure; predictable under some conditions | Low |
| Shuffles entire list to pick one item | Inefficient for large lists | Low |
| Cached image list may become stale | Different requests may use different list lengths | Low |

#### Publish Workflow: `execute()` (`core/workflow.py:95-241`)

```python
posted_hashes = load_posted_hashes()
posted_content_hashes = load_posted_content_hashes()
random.shuffle(images_with_hashes)

for name, ch in candidate_order:
    blob = await self.storage.download_image(...)
    digest = hashlib.sha256(blob).hexdigest()
    if digest in posted_hashes:
        continue  # Skip already-published
    selected_image = name
    break
```

**Positive:** The workflow tracks published images via SHA256 and Dropbox `content_hash` to prevent re-publishing duplicates.

**Gap:** This only tracks **published** images, not **viewed** images. A user browsing the web UI can see the same image repeatedly before publishing.

### 2. Dropbox API Ordering Behavior

The Dropbox `files_list_folder` API returns entries in a **deterministic internal order** (typically alphabetical by path). For a folder with sequentially named files:

```
IMG_0001.jpg
IMG_0002.jpg
IMG_0003.jpg
...
IMG_1000.jpg
```

The list always arrives in this order. When `random.shuffle()` is applied, adjacent items in the original list have **no special relationship** in the shuffled result—but user perception links "IMG_0500" and "IMG_0501" as "close" even if they were randomly selected independently.

### 3. Statistical Analysis: Birthday Paradox

For a pool of **N=1000 images**, the probability of seeing a repeat after **k** random selections:

| Selections (k) | P(at least one repeat) |
|----------------|------------------------|
| 10 | ~4.4% |
| 20 | ~17.4% |
| 30 | ~35.5% |
| 40 | ~54.0% |
| 50 | ~71.0% |

After just ~40 random views, there's a >50% chance a user will see a repeat. This is **expected behavior** for true randomness but feels "non-random" to humans.

### 4. Current Logging & Auditability

**Existing logging:**

```python
# web/app.py:329-336
log_json(
    logger,
    logging.INFO,
    "web_random_image",
    filename=img.filename,
    correlation_id=telemetry.correlation_id,
    web_random_image_ms=web_random_image_ms,
)
```

**Gaps:**
- No tenant/user identifier in random image logs
- No session context to correlate sequential views
- No persistent publication history queryable for audits
- Workflow timing logs exist but lack aggregation-friendly format

---

## Root Cause Summary

| Factor | Contribution | Fix Complexity |
|--------|--------------|----------------|
| No "recently shown" memory in web UI | **Primary** | Medium |
| Human clustering perception bias | Secondary (inherent) | Low (education) |
| Birthday paradox at N=1000 | Secondary (statistical) | Medium |
| Python `random` PRNG | Minor | Low |
| No publication audit log | Observability gap | Low |

---

## Proposed Solutions

### Solution 1: Recently-Shown Buffer (Recommended)

**Concept:** Track the last N images shown per tenant/session and exclude them from random selection.

**Implementation approach:**

```python
class RecentlyShownBuffer:
    """
    LRU buffer tracking recently-shown images per tenant.
    
    - Configurable buffer size (e.g., 50 images = ~5% of 1000)
    - Images in buffer are excluded from random selection
    - Buffer auto-expires after configurable TTL (e.g., 1 hour)
    """
    
    def __init__(self, max_size: int = 50, ttl_seconds: int = 3600):
        self._buffer: OrderedDict[str, float] = OrderedDict()
        self._max_size = max_size
        self._ttl = ttl_seconds
    
    def add(self, filename: str) -> None:
        """Record that filename was shown."""
        self._evict_expired()
        self._buffer[filename] = time.time()
        self._buffer.move_to_end(filename)
        while len(self._buffer) > self._max_size:
            self._buffer.popitem(last=False)
    
    def filter_candidates(self, images: List[str]) -> List[str]:
        """Return images not in recently-shown buffer."""
        self._evict_expired()
        return [img for img in images if img not in self._buffer]
```

**Modified `get_random_image()`:**

```python
async def get_random_image(self) -> ImageResponse:
    images = await self._get_cached_images()
    if not images:
        raise FileNotFoundError("No images found")
    
    # Exclude recently-shown images
    candidates = self._recently_shown.filter_candidates(images)
    if not candidates:
        # Fallback: if buffer exhausted entire list, reset and pick any
        candidates = images
        self._recently_shown.clear()
    
    import secrets
    selected = secrets.choice(candidates)  # Cryptographic randomness
    self._recently_shown.add(selected)
    ...
```

**Configuration:**

| Env Var | Default | Description |
|---------|---------|-------------|
| `RANDOM_BUFFER_SIZE` | 50 | Max images in recently-shown buffer |
| `RANDOM_BUFFER_TTL_SECONDS` | 3600 | Buffer entry expiry time |

**Benefits:**
- Guarantees no immediate repeats
- Buffer size controls "freshness window"
- Works per-tenant in orchestrator mode

### Solution 2: Cryptographic Randomness

**Replace:**
```python
import random
random.shuffle(images)
selected = images[0]
```

**With:**
```python
import secrets
selected = secrets.choice(images)
```

`secrets.SystemRandom` uses OS-level entropy (`/dev/urandom`) and is suitable for security-sensitive selection.

**Effort:** Low (one-line change)  
**Impact:** Marginal improvement in true randomness; psychological reassurance

### Solution 3: Publication History Log

**Concept:** Emit a structured publication event that can be aggregated for audits.

**Log format:**

```json
{
  "event": "image_published",
  "timestamp": "2026-01-12T14:30:00Z",
  "tenant": "alice",
  "host": "alice.shibari.photo",
  "filename": "IMG_0742.jpg",
  "sha256": "abc123...",
  "dropbox_content_hash": "def456...",
  "correlation_id": "uuid-...",
  "platforms": ["telegram", "fetlife_email"],
  "archived": true
}
```

**Benefits:**
- Queryable via log aggregation (Papertrail, Datadog, etc.)
- Enables "what was published when" audits
- Supports freshness analytics (time since last publish per tenant)

**Implementation:** Add `log_json()` call after successful publish in `workflow.py`.

### Solution 4: Visual Similarity Avoidance (Future Enhancement)

**Concept:** Use perceptual hashing (pHash) or image embeddings to avoid selecting visually similar images in sequence.

**Approach:**
1. Pre-compute perceptual hash for each image (store in sidecar or DB)
2. When selecting random image, compute Hamming distance to recently-shown
3. Deprioritize candidates within similarity threshold

**Complexity:** High (requires pre-processing pipeline)  
**Recommendation:** Defer to future feature; focus on Solutions 1-3 first

---

## Recommendation

### Phase 1 (Immediate)
1. **Implement Recently-Shown Buffer** (Solution 1) — addresses primary complaint
2. **Switch to `secrets.choice()`** (Solution 2) — low-effort improvement
3. **Add publication audit logging** (Solution 3) — enables verification

### Phase 2 (Future)
4. Consider visual similarity avoidance for premium tenants

### Acceptance Criteria

| AC | Description |
|----|-------------|
| AC1 | Web UI random selection excludes last N (default 50) images shown in current session/tenant |
| AC2 | Buffer size and TTL are configurable via env vars |
| AC3 | `secrets.choice()` is used for cryptographic randomness |
| AC4 | Publication events are logged with tenant, filename, hash, timestamp |
| AC5 | Unit tests verify buffer exclusion and edge cases (empty buffer, buffer larger than image count) |
| AC6 | No regression in existing workflow deduplication |

---

## Files to Modify

| File | Change |
|------|--------|
| `publisher_v2/src/publisher_v2/web/service.py` | Add `RecentlyShownBuffer`, modify `get_random_image()` |
| `publisher_v2/src/publisher_v2/core/workflow.py` | Add publication audit log, use `secrets` |
| `publisher_v2/src/publisher_v2/utils/state.py` | (Optional) Add `RecentlyShownBuffer` class |
| `publisher_v2/tests/web/test_random_selection.py` | New test file for buffer behavior |

---

## Test Plan

### Unit Tests

1. **Buffer exclusion**: Verify recently-shown images are excluded
2. **Buffer overflow**: Verify oldest entries are evicted at max_size
3. **Buffer expiry**: Verify entries older than TTL are ignored
4. **Empty candidates**: Verify fallback when buffer exhausts list
5. **Cryptographic choice**: Verify `secrets.choice` distribution (statistical test)

### Integration Tests

1. **Repeated random calls**: Call `/api/images/random` N times, verify no immediate repeats
2. **Cross-tenant isolation**: Verify buffer is per-tenant in orchestrator mode

### Manual Verification

1. User testing with ~100 random views to confirm subjective improvement
2. Log analysis to verify publication audit events are emitted

---

## References

- Python `secrets` module: https://docs.python.org/3/library/secrets.html
- Birthday paradox: https://en.wikipedia.org/wiki/Birthday_problem
- Dropbox API `files_list_folder`: https://www.dropbox.com/developers/documentation/http/documentation#files-list_folder
- Fisher-Yates shuffle: https://en.wikipedia.org/wiki/Fisher%E2%80%93Yates_shuffle

---

## Appendix: Code Snippets

### Current `get_random_image()` (web/service.py:265-276)

```python
async def get_random_image(self) -> ImageResponse:
    images = await self._get_cached_images()
    if not images:
        raise FileNotFoundError("No images found")

    import random
    random.shuffle(images)
    selected = images[0]
    folder = self.config.dropbox.image_folder

    temp_link = await self.storage.get_temporary_link(folder, selected)
    return await self._build_image_response(selected, temp_link)
```

### Current workflow selection (core/workflow.py:117-194)

```python
selection_start = now_monotonic()
posted_hashes = load_posted_hashes()
posted_content_hashes = load_posted_content_hashes()

# Shuffle to preserve existing randomization behavior
random.shuffle(images_with_hashes)
images = [name for name, _ in images_with_hashes]

# ... dedup loop ...
for name, ch in candidate_order:
    blob = await self.storage.download_image(self.config.dropbox.image_folder, name)
    digest = hashlib.sha256(blob).hexdigest()
    if digest in posted_hashes:
        continue
    selected_image = name
    content = blob
    selected_hash = digest
    selected_content_hash = ch or ""
    break
```

---

**Report prepared by:** Engineering Team  
**Next steps:** Create feature spec for Phase 1 implementation
