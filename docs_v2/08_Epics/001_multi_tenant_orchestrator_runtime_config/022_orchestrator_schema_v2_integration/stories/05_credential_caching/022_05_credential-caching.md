# Story 05 — Credential Caching

**Feature ID:** 022  
**Story ID:** 022-05  
**Status:** Shipped  
**Date:** 2025-12-25

---

## Context / Scope

Credential resolution via `/v1/credentials/resolve` returns secret material. To reduce latency and orchestrator load, Publisher should cache credentials in-memory with strict constraints:

**Agreed caching rules** (from issue #25):
- **Cache key**: `(tenant, credentials_ref, version)`
- **TTL**: min(runtime TTL, 10 minutes)
- **Never persist to disk**; honor `Cache-Control: no-store`
- First implementation can also resolve on-demand; caching is optional

This story implements the caching layer for resolved credentials.

**Parent feature:** [022_feature.md](../../022_feature.md)  
**Depends on:** Story 03 (Credential Resolution)

---

## Dependencies

| Story | Requirement |
|-------|-------------|
| 03 — Credential Resolution | Credential resolution logic exists (add caching layer) |

---

## Behaviour

### Preconditions

- Story 03 is implemented (credential resolution works)
- Runtime config caching exists (from Story 02)

### Main Flow

1. Create in-memory credential cache:
   - Key: `(tenant, credentials_ref, version)`
   - Value: `CredentialPayload` (typed credential data)
   - TTL: configurable via `CREDENTIAL_CACHE_TTL_SECONDS` (default 600), capped at runtime TTL
   - Max size: `CREDENTIAL_CACHE_MAX_SIZE` (default 5000), LRU eviction

2. On credential request:
   - Check cache for `(tenant, credentials_ref, version)`
   - If hit and not expired → return cached value
   - If miss or expired → resolve from orchestrator, cache result

3. Cache invalidation:
   - **TTL expiry**: Remove entry when TTL exceeded
   - **Version change**: If runtime config returns new `version` for a ref, invalidate old cache entry
   - **LRU eviction**: When max size reached, evict least recently used entries
   - **Process restart**: Cache is lost (in-memory only)

4. **Single-flight pattern** (prevent thundering herd):
   - If multiple concurrent requests need the same credential, only one resolution is in-flight
   - Other requests await the in-flight task
   - Prevents N concurrent requests from triggering N orchestrator calls

```python
class SingleFlight:
    """Coalesce concurrent requests for the same key."""
    _in_flight: Dict[str, asyncio.Task]
    
    async def do(self, key: str, fn: Callable) -> Any:
        if key in self._in_flight:
            return await self._in_flight[key]
        task = asyncio.create_task(fn())
        self._in_flight[key] = task
        try:
            return await task
        finally:
            del self._in_flight[key]
```

4. Honor `Cache-Control: no-store`:
   - Never write credentials to disk
   - Never write to external cache stores (Redis, etc.)
   - Only in-process memory

5. Add metrics/observability:
   - `credential_cache_hit_total` counter
   - `credential_cache_miss_total` counter
   - Log cache operations at DEBUG level (without secrets)

### Alternative Flows

- **On-demand resolution**: If caching is disabled (`CREDENTIAL_CACHE_ENABLED=False`), resolve on every request
- **Cache disabled for specific providers**: Could be extended, but not in MVP

### Error Flows

- **Cache corruption**: If cached value fails validation, treat as miss and re-resolve
- **Resolution failure with stale cache**: Do not serve stale credentials; fail the request

---

## Acceptance Criteria

- [ ] Credentials are cached in-memory with key `(tenant, credentials_ref, version)`
- [ ] Cache TTL defaults to 10 minutes and is configurable via `CREDENTIAL_CACHE_TTL_SECONDS`
- [ ] Cache TTL is capped at runtime config TTL (shorter of the two)
- [ ] Cache hit returns credentials without calling orchestrator
- [ ] Cache miss or expiry triggers fresh resolution
- [ ] Version change in runtime config invalidates related cache entries
- [ ] Credentials are never persisted to disk
- [ ] Cache metrics are exposed (hit/miss counters)
- [ ] No secrets appear in logs (even at DEBUG level)
- [ ] Unit tests verify caching behavior and TTL expiry
- [ ] Cache has max size limit with LRU eviction
- [ ] Single-flight pattern prevents concurrent resolution of same credential
- [ ] Unit tests verify single-flight coalesces concurrent requests

---

## Testing

### Manual Testing

1. Resolve credentials twice → verify second call is a cache hit (check logs/metrics)
2. Wait for TTL + 1 second → verify next call is a cache miss
3. Update credential in orchestrator (version changes) → verify new value is fetched
4. Restart Publisher → verify credentials are re-resolved (cache is empty)

### Automated Tests

Add/extend tests under `publisher_v2/tests/config/`:

- `test_credential_cache.py`:
  - `test_cache_stores_resolved_credentials`
  - `test_cache_hit_returns_without_api_call`
  - `test_cache_miss_triggers_resolution`
  - `test_cache_expiry_triggers_re_resolution`
  - `test_version_change_invalidates_cache`
  - `test_cache_respects_ttl_cap`
  - `test_cache_is_in_memory_only`
  - `test_cache_metrics_increment`
  - `test_cache_lru_eviction_when_max_size_reached`
  - `test_single_flight_coalesces_concurrent_requests`
  - `test_single_flight_does_not_cache_failures`

Use time mocking to test TTL behavior.

---

## Implementation Notes

### Files to Create/Modify

- **Create**: `publisher_v2/src/publisher_v2/config/credential_cache.py`
  - `CredentialCache` class
  - In-memory storage with TTL
  - Methods: `get()`, `set()`, `invalidate()`, `clear()`

- **Modify**: `publisher_v2/src/publisher_v2/config/source.py`
  - Integrate `CredentialCache` into `OrchestratorConfigSource`

### Cache Implementation Sketch

```python
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Tuple

@dataclass
class CacheEntry:
    payload: CredentialPayload
    expires_at: datetime
    version: str

class CredentialCache:
    def __init__(self, default_ttl_seconds: int = 600):
        self._cache: Dict[Tuple[str, str], CacheEntry] = {}
        self._default_ttl = timedelta(seconds=default_ttl_seconds)
    
    def get(self, tenant: str, credentials_ref: str, expected_version: str | None = None) -> CredentialPayload | None:
        key = (tenant, credentials_ref)
        entry = self._cache.get(key)
        
        if entry is None:
            return None
        
        if datetime.utcnow() > entry.expires_at:
            del self._cache[key]
            return None
        
        if expected_version and entry.version != expected_version:
            del self._cache[key]
            return None
        
        return entry.payload
    
    def set(self, tenant: str, credentials_ref: str, payload: CredentialPayload, version: str, ttl: timedelta | None = None):
        key = (tenant, credentials_ref)
        effective_ttl = min(ttl or self._default_ttl, self._default_ttl)
        self._cache[key] = CacheEntry(
            payload=payload,
            expires_at=datetime.utcnow() + effective_ttl,
            version=version
        )
    
    def invalidate(self, tenant: str, credentials_ref: str):
        key = (tenant, credentials_ref)
        self._cache.pop(key, None)
    
    def clear(self):
        self._cache.clear()
```

### Security Considerations

- Cache is **per-process** and **in-memory only**
- No serialization to disk or external stores
- Cache entries contain secrets → ensure no logging of cache contents
- On process shutdown, cache is automatically cleared

### Repo Rules

- **Secrets must never be logged** — Even cache operations must not log payload contents
- **No disk persistence** — Honor `Cache-Control: no-store`

---

## Change History

| Date | Change |
|------|--------|
| 2025-12-24 | Initial story draft |

