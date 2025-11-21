<!-- docs_v2/08_Features/08_04_ChangeRequests/005/007_design.md -->

# Change Design: Feature Toggle Button Visibility

**Change ID:** 005-007  
**Change Name:** feature-toggle-button-visibility  
**Parent Feature:** 005 (web-interface-mvp)  
**Design Version:** 1.0  
**Date:** 2025-11-21  
**Status:** Design Review  
**Author:** Architecture Team  

---

## 1. Overview

### Problem Recap

The web UI currently shows all publisher buttons regardless of configuration state. This creates UX friction:
- Visual clutter when users only enable a subset of publishers
- Confusion about which publishers are actually available
- No clear indication of system configuration state

### Solution Summary

Add a new API endpoint exposing publisher enablement state and modify the frontend to conditionally render publisher buttons based on that state. This is a pure presentation-layer change with no impact on business logic, configuration schema, or publishing behavior.

### Goals

1. **User Experience:** Clean, focused UI showing only available publishers
2. **Transparency:** UI accurately reflects backend configuration
3. **Simplicity:** Minimal code changes; leverage existing config structures
4. **Maintainability:** No duplication; single source of truth remains config

### Non-Goals

- Runtime publisher enable/disable (config remains static until restart)
- Per-user publisher visibility (single operator model)
- Publisher configuration UI or management features
- Changes to publishing logic or error handling

---

## 2. Context & Requirements

### Current State

**Configuration Schema** (`publisher_v2/src/publisher_v2/config/schema.py`):

```python
class PlatformsConfig(BaseModel):
    telegram_enabled: bool = False
    instagram_enabled: bool = False
    email_enabled: bool = False

class TelegramConfig(BaseModel):
    bot_token: str
    channel_id: str

# Similar for InstagramConfig, EmailConfig
```

**Web App** (`publisher_v2/src/publisher_v2/web/app.py`):
- FastAPI application with routes for image operations
- Config loaded at startup via `WebImageService`
- No current endpoint exposing publisher state

**Frontend** (`publisher_v2/src/publisher_v2/web/templates/index.html`):
- Single-page HTML with embedded JavaScript
- Statically renders all publisher buttons
- No awareness of backend configuration state

### Requirements

**Functional:**
1. New endpoint `GET /api/config/publishers` returning publisher enablement state
2. Frontend fetches publisher state on load
3. Publisher buttons render conditionally based on state
4. Graceful degradation on API errors

**Non-Functional:**
1. Response time < 50ms (in-memory config read)
2. No authentication required (non-sensitive boolean flags)
3. Backward compatible (additive API change only)
4. No impact on existing endpoints or CLI behavior

### Constraints

- Must reuse existing `ApplicationConfig` structure (no schema changes)
- Must preserve single source of truth: config file and env vars
- Must maintain stateless web layer (no server-side session state)
- Must not expose secrets or sensitive configuration details

---

## 3. Detailed Design

### 3.1 Backend Changes

#### New Endpoint: `GET /api/config/publishers`

**Location:** `publisher_v2/src/publisher_v2/web/app.py`

**Implementation:**

```python
@app.get("/api/config/publishers")
async def api_get_publishers_config(
    service: WebImageService = Depends(get_service)
) -> dict[str, bool]:
    """
    Return enablement state for all configured publishers.
    
    Returns a dict mapping publisher names to enabled state.
    No authentication required (non-sensitive configuration flags).
    """
    config = service.config
    return {
        "telegram": config.platforms.telegram_enabled and config.telegram is not None,
        "email": config.platforms.email_enabled and config.email is not None,
        "instagram": config.platforms.instagram_enabled and config.instagram is not None,
    }
```

**Logic:**
- Read from existing `ApplicationConfig` via `WebImageService`
- Check both `platforms.<publisher>_enabled` flag AND presence of publisher-specific config
- Return simple `{publisher_name: bool}` mapping

**Response Schema:**

```json
{
  "telegram": true,
  "email": false,
  "instagram": true
}
```

**Error Handling:**
- No expected errors (config is validated at startup)
- If config access fails, FastAPI default 500 handler applies
- Frontend handles 500 by defaulting to showing all buttons (defensive)

**Security:**
- No authentication required (public read of non-sensitive flags)
- Does not expose tokens, passwords, or other secrets
- Only exposes boolean enablement state

**Performance:**
- In-memory config read: O(1)
- Response size: ~50-100 bytes
- Expected latency: <10ms

#### Service Layer

**No changes required.** The endpoint directly accesses `service.config`, which is already available via `WebImageService.config`.

### 3.2 Frontend Changes

#### Fetch Publisher Config on Page Load

**Location:** `publisher_v2/src/publisher_v2/web/templates/index.html`

**New JavaScript Function:**

```javascript
async function fetchPublisherConfig() {
    try {
        const response = await fetch('/api/config/publishers');
        if (!response.ok) {
            console.warn('Failed to fetch publisher config, showing all buttons');
            return { telegram: true, email: true, instagram: true };
        }
        return await response.json();
    } catch (error) {
        console.error('Error fetching publisher config:', error);
        // Default to showing all buttons on error
        return { telegram: true, email: true, instagram: true };
    }
}
```

**Integration into Page Load:**

```javascript
// On page load
document.addEventListener('DOMContentLoaded', async () => {
    const publisherConfig = await fetchPublisherConfig();
    
    // Store in app state
    window.publisherConfig = publisherConfig;
    
    // Render initial UI
    renderPublisherButtons();
    
    // ... rest of initialization
});
```

#### Conditional Button Rendering

**Current State:**
```html
<!-- All buttons always visible -->
<div class="actions">
    <button id="btn-publish-telegram">Publish to Telegram</button>
    <button id="btn-publish-email">Publish to Email</button>
    <button id="btn-publish-instagram">Publish to Instagram</button>
</div>
```

**New State:**
```javascript
function renderPublisherButtons() {
    const container = document.getElementById('publisher-actions');
    container.innerHTML = ''; // Clear existing buttons
    
    const publisherConfig = window.publisherConfig || {};
    
    if (publisherConfig.telegram) {
        const btn = createButton('Publish to Telegram', 'telegram');
        container.appendChild(btn);
    }
    
    if (publisherConfig.email) {
        const btn = createButton('Publish to Email', 'email');
        container.appendChild(btn);
    }
    
    if (publisherConfig.instagram) {
        const btn = createButton('Publish to Instagram', 'instagram');
        container.appendChild(btn);
    }
    
    // If no publishers enabled, show a message
    if (!publisherConfig.telegram && !publisherConfig.email && !publisherConfig.instagram) {
        container.innerHTML = '<p class="info">No publishers configured</p>';
    }
}

function createButton(label, platform) {
    const btn = document.createElement('button');
    btn.textContent = label;
    btn.className = `btn btn-publish btn-publish-${platform}`;
    btn.addEventListener('click', () => handlePublish(platform));
    return btn;
}
```

#### Handling Config Changes

**Scenario:** User changes config and restarts app.

**Behavior:**
- On page refresh, frontend fetches new config
- Buttons render according to new state
- No client-side caching between page reloads

**Implementation:** Already handled by `fetchPublisherConfig()` on `DOMContentLoaded`.

#### Error States

**API Unavailable:**
- Log warning to console
- Default to showing all buttons (graceful degradation)
- User can still attempt publish (backend will return appropriate error)

**No Publishers Enabled:**
- Show friendly message: "No publishers configured"
- Admin controls (analyze, etc.) remain functional

---

## 4. Data Flow

### Startup Flow

```
1. User requests web UI (GET /)
2. Server returns index.html
3. Browser executes JavaScript:
   a. Call GET /api/config/publishers
   b. Store result in window.publisherConfig
   c. Call renderPublisherButtons()
   d. Only enabled publisher buttons appear
```

### Publish Flow (Unchanged)

```
1. User clicks visible "Publish to Telegram" button
2. Frontend calls POST /api/images/{filename}/publish
3. Backend validates auth, checks config, executes publish
4. Response indicates success/failure per platform
```

### Config Change Flow

```
1. Operator edits config file (e.g., disables Email)
2. Operator restarts web app
3. User refreshes browser page
4. Frontend fetches new config
5. Email button no longer rendered
```

---

## 5. API Contract

### New Endpoint

**`GET /api/config/publishers`**

**Request:**
- Method: `GET`
- Path: `/api/config/publishers`
- Headers: None required
- Body: None

**Response (200 OK):**
```json
{
  "telegram": true,
  "email": false,
  "instagram": true
}
```

**Response Schema:**
- Type: `object`
- Keys: `"telegram"`, `"email"`, `"instagram"`
- Values: `boolean` (true if enabled and configured, false otherwise)

**Error Responses:**
- `500 Internal Server Error`: Unexpected backend error (rare; config validated at startup)

**Caching:**
- No caching headers (stateless; config changes require app restart anyway)
- Frontend caches in memory for session duration

**Versioning:**
- No version in URL (additive change; backward compatible)
- Future publishers can be added to response without breaking existing clients

---

## 6. Testing Strategy

### Unit Tests

**Backend:**

File: `publisher_v2/tests/web/test_web_app.py`

```python
def test_get_publishers_config_all_enabled(test_client, mock_service):
    """All publishers enabled returns all true."""
    mock_service.config.platforms.telegram_enabled = True
    mock_service.config.platforms.email_enabled = True
    mock_service.config.platforms.instagram_enabled = True
    mock_service.config.telegram = TelegramConfig(bot_token="...", channel_id="...")
    mock_service.config.email = EmailConfig(sender="...", recipient="...", password="...")
    mock_service.config.instagram = InstagramConfig(username="...", password="...")
    
    response = test_client.get("/api/config/publishers")
    
    assert response.status_code == 200
    data = response.json()
    assert data == {"telegram": True, "email": True, "instagram": True}


def test_get_publishers_config_partial(test_client, mock_service):
    """Only Telegram enabled."""
    mock_service.config.platforms.telegram_enabled = True
    mock_service.config.platforms.email_enabled = False
    mock_service.config.platforms.instagram_enabled = False
    mock_service.config.telegram = TelegramConfig(bot_token="...", channel_id="...")
    mock_service.config.email = None
    mock_service.config.instagram = None
    
    response = test_client.get("/api/config/publishers")
    
    assert response.status_code == 200
    data = response.json()
    assert data == {"telegram": True, "email": False, "instagram": False}


def test_get_publishers_config_none_enabled(test_client, mock_service):
    """No publishers enabled."""
    mock_service.config.platforms.telegram_enabled = False
    mock_service.config.platforms.email_enabled = False
    mock_service.config.platforms.instagram_enabled = False
    
    response = test_client.get("/api/config/publishers")
    
    assert response.status_code == 200
    data = response.json()
    assert data == {"telegram": False, "email": False, "instagram": False}
```

**Frontend:**

Manual testing (no JS unit test framework in MVP):
1. Mock API to return `{"telegram": true, "email": false, "instagram": false}`
2. Load page
3. Verify only Telegram button visible

### Integration Tests

File: `publisher_v2/tests/web/test_web_integration.py`

```python
@pytest.mark.asyncio
async def test_publisher_button_visibility_workflow():
    """
    End-to-end test: fetch config, verify buttons match, publish works.
    """
    # Setup: config with only Telegram enabled
    # ...
    
    # Fetch config
    config_response = test_client.get("/api/config/publishers")
    assert config_response.json() == {"telegram": True, "email": False, "instagram": False}
    
    # Simulate frontend: only render Telegram button
    # (manual verification in browser test)
    
    # Publish via Telegram should work
    publish_response = test_client.post(
        "/api/images/test.jpg/publish",
        json={"platforms": ["telegram"]},
        headers=auth_headers,
    )
    assert publish_response.status_code == 200
    
    # Publish via Email should fail (not configured)
    # (backend validation, not UI visibility)
```

### Manual Tests

**Test Case 1: All Publishers Enabled**
1. Configure all publishers in config file
2. Restart web app
3. Load UI in browser
4. **Expected:** All three publisher buttons visible
5. Click each button, verify publish succeeds

**Test Case 2: Only Telegram Enabled**
1. Configure only Telegram
2. Restart web app
3. Load UI in browser
4. **Expected:** Only Telegram button visible
5. Click Telegram button, verify publish succeeds

**Test Case 3: No Publishers Enabled**
1. Disable all publishers in config
2. Restart web app
3. Load UI in browser
4. **Expected:** No publisher buttons; message "No publishers configured"
5. Analyze button still functional (if admin)

**Test Case 4: API Error Handling**
1. Simulate API failure (e.g., kill backend after page load)
2. Refresh page
3. **Expected:** Console warning; all buttons shown (fallback)

**Test Case 5: Config Change Workflow**
1. Start with Telegram enabled
2. Load UI, verify Telegram button visible
3. Edit config to disable Telegram, enable Email
4. Restart web app
5. Refresh browser
6. **Expected:** Email button visible, Telegram button gone

---

## 7. Security & Privacy

### Threat Analysis

| Threat | Mitigation |
|--------|-----------|
| Exposure of publisher credentials | Endpoint returns only boolean flags; no tokens/passwords |
| Unauthorized config modification | Config is read-only from web layer; requires file system access to modify |
| Information disclosure about system setup | Publisher names (telegram/email/instagram) are not sensitive; enablement state is operational metadata |

### Authentication

**Decision:** No authentication required for `/api/config/publishers`.

**Rationale:**
- Endpoint exposes only non-sensitive boolean flags
- Does not grant any privilege or enable actions
- Aligns with principle of "least surprise" (UI should accurately reflect capabilities)
- Mutating actions (publish, analyze) remain protected

### Logging

**New Log Events:**

```python
log_json(logger, logging.DEBUG, "web_publishers_config_requested")
```

No sensitive data logged (only event occurrence).

---

## 8. Performance & Scalability

### Latency

**Backend:**
- Config read: In-memory access, O(1)
- JSON serialization: 3 boolean fields, ~50 bytes
- **Expected P95:** <10ms

**Frontend:**
- Network request: Dependent on RTT
- JSON parse: Trivial (50 bytes)
- Button rendering: O(n) where n=3, negligible
- **Expected P95:** <100ms total (including network)

### Caching

**Backend:** No caching needed (in-memory config read is fast).

**Frontend:** Config stored in `window.publisherConfig` for session; refreshed on page reload.

**Future Enhancement:** Add `Cache-Control: max-age=300` header to reduce requests on multi-page apps (not applicable to single-page MVP).

### Scalability

**Impact:** None. Endpoint is stateless, read-only, and fast. Scales horizontally with FastAPI app.

---

## 9. Observability

### Metrics

**Existing:**
- Standard web request metrics (endpoint hit count, latency, status codes)

**New (Optional):**
- Count of `/api/config/publishers` requests
- Publisher config fetch errors (5xx responses)

**Implementation:** Use existing structured logging; parse logs for metrics.

### Logging

**New Events:**
- `web_publishers_config_requested` (DEBUG level)
- `web_publishers_config_error` (ERROR level, if unexpected exception)

**Existing Events (Unchanged):**
- `web_random_image`, `web_analyze_complete`, `web_publish_complete`

### Dashboards

No new dashboards required. Existing web telemetry covers this endpoint.

---

## 10. Risks & Mitigations

| Risk | Impact | Likelihood | Mitigation |
|------|--------|------------|------------|
| API endpoint fails, UI breaks | Medium | Low | Frontend defaults to showing all buttons on error |
| Config changes not reflected without refresh | Low | Medium | Document refresh requirement; consider future SSE/polling |
| Confusion if publisher button missing | Low | Low | Show "No publishers configured" message when all disabled |
| Breaking change for existing users | Low | Low | Additive API change; no existing endpoint modified |

---

## 11. Alternatives Considered

### Alternative 1: Embed Config in HTML at Render Time

**Approach:** Server-side template renders config into HTML (e.g., `<script>window.publisherConfig = {...}</script>`).

**Pros:**
- No extra API call
- Config available immediately

**Cons:**
- Couples config to HTML rendering
- Harder to cache HTML
- Less separation of concerns

**Decision:** Rejected. API endpoint provides better separation and enables future enhancements (e.g., live config updates via polling).

### Alternative 2: Show All Buttons, Disable Unavailable Ones

**Approach:** Render all buttons but disable (gray out) those not configured.

**Pros:**
- User sees all available options
- Clear visual indication of disabled state

**Cons:**
- Visual clutter (user request explicitly wants to hide buttons)
- Confusion about why buttons are disabled
- Violates principle of "show only what's available"

**Decision:** Rejected. User story explicitly requests hiding, not disabling.

### Alternative 3: Dynamic Publisher List (No Hardcoded Names)

**Approach:** Backend returns list of all registered publishers (via plugin registry or similar).

**Pros:**
- Extensible to new publishers without code changes

**Cons:**
- Over-engineering for MVP (only 3 publishers)
- Requires plugin architecture (not in current design)

**Decision:** Deferred. Hardcoded list is acceptable for MVP; can evolve to dynamic system in future.

---

## 12. Implementation Plan

### Files to Modify

1. **Backend:**
   - `publisher_v2/src/publisher_v2/web/app.py`: Add `api_get_publishers_config()` endpoint

2. **Frontend:**
   - `publisher_v2/src/publisher_v2/web/templates/index.html`:
     - Add `fetchPublisherConfig()` function
     - Add `renderPublisherButtons()` function
     - Update DOMContentLoaded handler

3. **Tests:**
   - `publisher_v2/tests/web/test_web_app.py`: Add unit tests for new endpoint
   - Manual test plan documented in this design

### Task Breakdown

1. **Backend endpoint** (~30 min):
   - Add route to `app.py`
   - Write logic to extract publisher state from config
   - Return JSON response

2. **Frontend fetch** (~20 min):
   - Add `fetchPublisherConfig()` function
   - Integrate into page load
   - Store in `window.publisherConfig`

3. **Frontend rendering** (~40 min):
   - Refactor button creation into `renderPublisherButtons()`
   - Implement conditional rendering logic
   - Add "No publishers configured" message

4. **Tests** (~60 min):
   - Write 3 unit tests for endpoint (all/partial/none enabled)
   - Manual testing with various configs

5. **Documentation** (~10 min):
   - Update `ARCHITECTURE.md` or `CONFIGURATION.md` to mention new endpoint

**Total Estimate:** ~2.5 hours

### Dependencies

- No external dependencies (uses existing FastAPI, config, web service)
- No schema changes
- No migration required

---

## 13. Definition of Done

- [ ] Endpoint `GET /api/config/publishers` implemented and returns correct enablement state
- [ ] Frontend fetches publisher config on page load
- [ ] Publisher buttons render conditionally based on config
- [ ] "No publishers configured" message shown when all disabled
- [ ] Error handling: API failure defaults to showing all buttons
- [ ] Unit tests pass (3 tests for endpoint)
- [ ] Manual tests pass (all 5 test cases)
- [ ] No regression in existing endpoints or CLI behavior
- [ ] Structured logs for new endpoint (if desired)
- [ ] Documentation updated (if applicable)

---

## 14. Appendices

### Glossary

- **Publisher:** A platform integration (Telegram, Email, Instagram) that publishes content
- **Enablement state:** Boolean flag indicating if a publisher is configured and active
- **Conditional rendering:** UI technique to show/hide elements based on state

### References

- Parent Feature Request: `docs_v2/08_Features/08_01_Feature_Request/005_web-interface-mvp.md`
- Parent Feature Design: `docs_v2/08_Features/08_02_Feature_Design/005_web-interface-mvp_design.md`
- Config Schema: `publisher_v2/src/publisher_v2/config/schema.py` (lines 91-148)
- Web App: `publisher_v2/src/publisher_v2/web/app.py`
- Related Changes:
  - 005-001: Web Interface Admin Controls
  - 005-003: Web UI Admin Visibility & Responsive Layout

### Example Payloads

**Request:**
```http
GET /api/config/publishers HTTP/1.1
Host: localhost:8000
```

**Response (All Enabled):**
```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "telegram": true,
  "email": true,
  "instagram": true
}
```

**Response (Only Telegram):**
```http
HTTP/1.1 200 OK
Content-Type: application/json

{
  "telegram": true,
  "email": false,
  "instagram": false
}
```

---

**End of Change Design Document**

