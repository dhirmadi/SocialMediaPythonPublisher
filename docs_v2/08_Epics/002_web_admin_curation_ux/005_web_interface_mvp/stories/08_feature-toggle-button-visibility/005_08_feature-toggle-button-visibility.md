<!-- docs_v2/08_Epics/08_04_ChangeRequests/005/007_feature-toggle-button-visibility.md -->

# Feature Toggle Button Visibility

**Change ID:** 005-007  
**Change Name:** feature-toggle-button-visibility  
**Parent Feature:** 005 (web-interface-mvp)  
**Status:** Shipped  
**Date:** 2025-11-21  
**Author:** Evert  
**Shipped:** 2025-11-21

---

## Summary

Publisher buttons in the web UI now conditionally render based on configuration state. When a publisher (Telegram, Email, Instagram) is disabled in the configuration, its button is completely hidden from the interface, providing a cleaner, less cluttered user experience.

---

## Problem Statement

The web interface was showing all publisher buttons regardless of whether the publishers were enabled in configuration. This created:
- Visual clutter for users who only enable a subset of publishers
- Confusion about which publishers are actually available
- No clear visual indication of system configuration state

---

## Solution

Added a new REST API endpoint `/api/config/publishers` that returns the enablement state of all publishers, and modified the frontend to fetch this state on page load and conditionally render only the buttons for enabled publishers.

### Backend Changes

**New Endpoint: `GET /api/config/publishers`**

Returns JSON mapping publisher names to boolean enablement state:

```json
{
  "telegram": true,
  "email": false,
  "instagram": true
}
```

Logic: A publisher is considered enabled if BOTH:
1. `platforms.<publisher>_enabled` flag is `true`
2. Publisher-specific config object is not `None`

**Implementation:** `publisher_v2/src/publisher_v2/web/app.py` (lines 312-327)

### Frontend Changes

**Modified:** `publisher_v2/src/publisher_v2/web/templates/index.html`

1. Added `fetchPublisherConfig()` function to call the new endpoint
2. Added `renderPublisherButtons()` function to create buttons only for enabled publishers
3. Publisher buttons now render dynamically on page load
4. Shows "No publishers configured" message when all publishers disabled
5. Graceful error handling: defaults to showing all buttons if API fails

---

## Technical Details

### API Contract

**Request:**
```http
GET /api/config/publishers HTTP/1.1
```

**Response (200 OK):**
```json
{
  "telegram": true,
  "email": false,
  "instagram": true
}
```

**Authentication:** None required (non-sensitive boolean flags)

**Performance:** <10ms (in-memory config read)

### Data Flow

```
1. User opens web UI
2. Page loads, calls GET /api/config/publishers
3. Backend reads config.platforms and publisher-specific configs
4. Backend returns enablement state as JSON
5. Frontend stores state in window.publisherConfig
6. Frontend calls renderPublisherButtons()
7. Only enabled publisher buttons appear in UI
```

### Error Handling

- **API failure:** Frontend logs warning and defaults to showing all buttons
- **No publishers enabled:** UI shows "No publishers configured" message
- **Config change:** Requires page refresh to reflect new state

---

## Files Modified

### Backend
- `publisher_v2/src/publisher_v2/web/app.py`: Added `api_get_publishers_config()` endpoint

### Frontend
- `publisher_v2/src/publisher_v2/web/templates/index.html`:
  - Added `fetchPublisherConfig()` function
  - Added `renderPublisherButtons()` function
  - Modified `initLayout()` to fetch config on page load
  - Updated `disableButtons()` and `updateAdminUI()` to work with dynamic buttons
  - Modified `apiPublish()` to accept platform parameter

### Tests
- `publisher_v2/tests/web/test_web_service.py`: Added 4 unit tests for endpoint logic
- `publisher_v2/tests/web/test_publishers_endpoint.py`: Added 3 integration tests for endpoint

### Documentation
- `docs_v2/03_Architecture/ARCHITECTURE.md`: Added `/api/config/publishers` to web API section

---

## Test Coverage

### Unit Tests (4)
1. `test_get_publishers_config_all_enabled`: All publishers enabled returns all `true`
2. `test_get_publishers_config_partial`: Subset of publishers enabled
3. `test_get_publishers_config_none_enabled`: No publishers enabled returns all `false`
4. `test_get_publishers_config_enabled_but_not_configured`: Enabled flag `true` but config `None` returns `false`

### Integration Tests (3)
1. `test_api_config_publishers_returns_correct_state`: Endpoint returns correct JSON
2. `test_api_config_publishers_no_auth_required`: Endpoint accessible without auth
3. `test_api_config_publishers_returns_json`: Endpoint returns valid JSON schema

### Test Results
- All 28 web tests pass (7 new tests added)
- 69% coverage for web module
- No regressions in existing functionality

---

## Acceptance Criteria

✅ **AC1:** Given Telegram enabled and Email/Instagram disabled, when user loads UI, then only Telegram button visible

✅ **AC2:** Given all publishers enabled, when user loads UI, then all buttons visible (no regression)

✅ **AC3:** Given all publishers disabled, when user loads UI, then no buttons visible and message shown

✅ **AC4:** Given API endpoint fails, when user loads UI, then graceful degradation (show all buttons)

✅ **AC5:** Given visible publisher button, when clicked, then publish succeeds (no regression)

✅ **AC6:** Given config changed and page refreshed, when user loads UI, then button visibility updated

---

## User Impact

**Before:** All three publisher buttons (Telegram, Email, Instagram) always visible regardless of configuration.

**After:** Only buttons for enabled publishers are shown. Cleaner UI, less confusion.

**Example Scenarios:**

- User only uses Telegram → Sees only Telegram button
- User uses Telegram + Instagram → Sees both buttons, Email hidden
- User has all publishers disabled → Sees "No publishers configured" message

---

## Deployment Notes

- **No migration required:** Additive API change only
- **No config changes required:** Uses existing configuration schema
- **Backward compatible:** Existing endpoints and CLI unchanged
- **Rollback safe:** No data changes or state modifications

---

## Security Considerations

- Endpoint returns only boolean enablement flags (non-sensitive)
- No authentication required (aligns with read-only public info)
- Does not expose tokens, credentials, or other secrets
- Only exposes publisher names (telegram/email/instagram) and enabled state

---

## Performance

- **Endpoint latency:** <10ms (in-memory config read)
- **Response size:** ~50-100 bytes
- **Frontend overhead:** <100ms including network request
- **No caching needed:** Config changes require app restart anyway

---

## Observability

**Logs:** No specific logging added (DEBUG-level log could be added if needed)

**Metrics:** Standard web request metrics apply:
- Request count for `/api/config/publishers`
- Latency distribution
- Error rate (should be near 0%)

---

## Known Limitations

1. **Config changes require app restart:** Dynamic config reload not implemented
2. **Page refresh required:** Changes don't reflect without refreshing browser
3. **No per-user visibility:** Single-operator model; all users see same buttons
4. **Hardcoded publisher list:** Not extensible to new publishers without code change (acceptable for MVP)

---

## Future Enhancements

- SSE or polling for live config updates
- Dynamic publisher registration (plugin architecture)
- Per-user publisher visibility (multi-tenant model)
- Cache-Control headers for improved performance
- Admin UI for managing publisher configuration

---

## Related Changes

- **005-001:** Web Interface Admin Controls
- **005-003:** Web UI Admin Visibility & Responsive Layout  
- **005-006:** Admin Button Position & Visibility

This change extends the pattern of conditional visibility established in these prior changes to cover publisher-specific buttons.

---

## Artifacts

**Change Request:** `docs_v2/08_Epics/08_04_ChangeRequests/005/007_feature-toggle-button-visibility.md`

**Change Design:** `docs_v2/08_Epics/08_04_ChangeRequests/005/007_design.md`

**Change Plan:** `docs_v2/08_Epics/08_04_ChangeRequests/005/007_plan.yaml`

**Implementation:**
- Backend: `publisher_v2/src/publisher_v2/web/app.py` (lines 312-327)
- Frontend: `publisher_v2/src/publisher_v2/web/templates/index.html` (multiple sections)
- Tests: `publisher_v2/tests/web/test_web_service.py`, `publisher_v2/tests/web/test_publishers_endpoint.py`
- Docs: `docs_v2/03_Architecture/ARCHITECTURE.md`

---

## References

- Parent Feature Request: `docs_v2/08_Epics/08_01_Feature_Request/005_web-interface-mvp.md`
- Parent Feature Design: `docs_v2/08_Epics/08_02_Feature_Design/005_web-interface-mvp_design.md`
- Configuration Schema: `publisher_v2/src/publisher_v2/config/schema.py`
- Repo Rules: `.cursor/rules/*.mdc` (canonical) and `.cursorrules` (compatibility shim)

---

**End of Change Documentation**
