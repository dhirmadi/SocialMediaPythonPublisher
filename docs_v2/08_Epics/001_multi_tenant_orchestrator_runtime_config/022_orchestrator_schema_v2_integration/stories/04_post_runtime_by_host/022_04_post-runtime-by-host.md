# Story 04 — POST Runtime By Host

**Feature ID:** 022  
**Story ID:** 022-04  
**Status:** Shipped  
**Date:** 2025-12-25

---

## Context / Scope

The orchestrator now supports `POST /v1/runtime/by-host` with JSON body `{ "host": "..." }` as an alternative to `GET /v1/runtime/by-host?host=...`.

**Agreed preference** (from issue #25):
- Use **POST as the default** in production to reduce query-string logging risk
- Fall back to **GET** if POST returns 405 (for orchestrator version compatibility)

Publisher doesn't rely on intermediary caches (in-process caching), so POST's "not cache-friendly" characteristic is not a concern.

**Parent feature:** [022_feature.md](../../022_feature.md)  
**Depends on:** Story 02 (Schema V2 Parsing)

---

## Dependencies

| Story | Requirement |
|-------|-------------|
| 02 — Schema V2 Parsing | Runtime config fetch logic exists (modify to prefer POST) |

---

## Behaviour

### Preconditions

- Story 02 is implemented (runtime config fetch exists)
- Orchestrator Feature 12 (POST runtime-by-host) is deployed

### Main Flow

1. Add configuration option:
   - `ORCHESTRATOR_PREFER_POST` — boolean, default `True`

2. Modify runtime config fetch logic:
   - If `ORCHESTRATOR_PREFER_POST=True`:
     - First attempt: `POST /v1/runtime/by-host` with body `{ "host": "<normalized_host>" }`
     - If 405 (Method Not Allowed): fall back to GET
   - If `ORCHESTRATOR_PREFER_POST=False`:
     - Use `GET /v1/runtime/by-host?host=<normalized_host>`

3. Implement fallback:
   - On 405 response, log warning "Orchestrator does not support POST runtime-by-host, falling back to GET"
   - Cache the fallback decision per-process (avoid repeated POST attempts after 405)
   - Retry the request using GET

4. Response handling:
   - POST and GET return identical response shapes
   - Parse using existing v1/v2 logic from Story 02

### Alternative Flows

- **GET-only mode**: If `ORCHESTRATOR_PREFER_POST=False`, skip POST entirely
- **Orchestrator pre-Feature-12**: If orchestrator returns 405, gracefully degrade to GET

### Error Flows

- **405 on POST**: Log warning, fall back to GET, cache fallback decision
- **Other errors (404, 403, 5xx)**: Handle as in Story 02 (do not interpret as "try GET")

---

## Acceptance Criteria

- [ ] `ORCHESTRATOR_PREFER_POST` config option defaults to `True`
- [ ] When `True`, POST is attempted first with JSON body `{ "host": "..." }`
- [ ] 405 response triggers fallback to GET with query parameter
- [ ] Fallback decision is cached per-process (no repeated POST attempts after 405)
- [ ] When `False`, GET is used directly
- [ ] Response parsing is identical for POST and GET
- [ ] Warning is logged when falling back from POST to GET
- [ ] Unit tests cover POST success, 405 fallback, and GET-only mode
- [ ] No host values appear in logs (use tenant instead)

---

## Testing

### Manual Testing

1. Point Publisher at orchestrator staging with POST support → verify POST is used (check orchestrator logs)
2. Set `ORCHESTRATOR_PREFER_POST=False` → verify GET is used
3. Point Publisher at older orchestrator without POST → verify fallback to GET after 405

### Automated Tests

Add/extend tests under `publisher_v2/tests/config/`:

- `test_post_runtime_by_host.py`:
  - `test_post_preferred_uses_post_method`
  - `test_post_405_falls_back_to_get`
  - `test_post_fallback_cached_per_process`
  - `test_prefer_post_false_uses_get_directly`
  - `test_post_body_contains_normalized_host`
  - `test_response_parsing_identical_for_post_and_get`

Use `httpx` mock/respx to simulate responses.

---

## Implementation Notes

### Files to Create/Modify

- **Modify**: `publisher_v2/src/publisher_v2/config/orchestrator_client.py`
  - Add `_prefer_post` flag (from config)
  - Add `_post_supported` cached flag (per-process)
  - Implement POST-first-then-GET logic

- **Modify**: `publisher_v2/src/publisher_v2/config/source.py`
  - Pass `ORCHESTRATOR_PREFER_POST` to orchestrator client

### Request Shapes

**POST request:**
```http
POST /v1/runtime/by-host HTTP/1.1
Authorization: Bearer <token>
X-Request-Id: <uuid>
Content-Type: application/json

{ "host": "xxx.shibari.photo" }
```

**GET request (fallback):**
```http
GET /v1/runtime/by-host?host=xxx.shibari.photo HTTP/1.1
Authorization: Bearer <token>
X-Request-Id: <uuid>
```

### Fallback Caching Strategy

```python
class OrchestratorClient:
    _post_supported: bool | None = None  # None = unknown, True = yes, False = 405 received
    
    async def get_runtime_config(self, host: str) -> OrchestratorRuntimeResponse:
        if self._prefer_post and self._post_supported is not False:
            try:
                response = await self._post_runtime(host)
                self._post_supported = True
                return response
            except MethodNotAllowedError:
                logger.warning("POST runtime-by-host not supported, falling back to GET")
                self._post_supported = False
        
        return await self._get_runtime(host)
```

### Repo Rules

- **Safe logging**: Do not log host in query string; log tenant separately
- **Async hygiene**: Use `httpx.AsyncClient`

---

## Change History

| Date | Change |
|------|--------|
| 2025-12-24 | Initial story draft |

