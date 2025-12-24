<!-- docs_v2/08_Epics/08_04_ChangeRequests/005/008_design.md -->

# AUTO_VIEW Anonymous Image Access — Change Design

**Feature ID:** 005  
**Change ID:** 005-008  
**Parent Feature:** Web Interface MVP  
**Design Version:** 1.0  
**Date:** 2025-11-21  
**Status:** Design Review  
**Author:** Evert  
**Linked Change Request:** docs_v2/08_Epics/08_04_ChangeRequests/005/008_auto-view-anonymous-image-access.md  
**Parent Feature Design:** docs_v2/08_Epics/08_02_Feature_Design/005_web-interface-mvp_design.md  

## 1. Summary

- **Problem & context:** The web interface currently allows anyone who can reach `/` to load a random image via `GET /api/images/random`, regardless of admin login state. Admin mode already protects analysis, publishing, curation, and detailed status, but image content itself may still be sensitive. Operators need a simple way to choose between a strictly private mode (images only for logged-in admin) and a relaxed mode (images visible to any viewer) without altering publishers or orchestrator behavior.  
- **Change:** Introduce an `AUTO_VIEW` environment flag, surfaced through the existing typed feature configuration and `/api/config/features` endpoint, and enforce it in both the backend (`/api/images/random`) and frontend (Next Image behavior and messaging).  
- **Goals:** Default to a **private** posture (`AUTO_VIEW=false`) where images require admin login, while still supporting a **viewer-friendly** mode (`AUTO_VIEW=true`) for trusted environments, and keep the implementation small, additive, and consistent with existing web/admin patterns.

## 2. Context & Assumptions

- **Current behavior (relevant pieces):**
  - `publisher_v2.web.app.api_get_random_image`:
    - Does **not** call `require_auth` or `require_admin`.
    - Always attempts to return a random image (404 on empty folder, 5xx on errors).
  - Admin mode is implemented via:
    - `.env` password `web_admin_pw`.
    - Cookie `pv2_admin` with TTL controlled by `WEB_ADMIN_COOKIE_TTL_SECONDS` (clamped 60–3600s).
    - Endpoints: `/api/admin/login`, `/api/admin/status`, `/api/admin/logout`.
    - Helpers in `publisher_v2.web.auth`: `is_admin_configured`, `require_admin`, `is_admin_request`, `set_admin_cookie`, `clear_admin_cookie`.
  - The HTML/JS template (`index.html`) already:
    - Maintains an `isAdmin` flag in JS.
    - Hides admin-only panels and buttons when not admin.
    - Uses `/api/admin/status` and 401/403 responses to track admin expiry.
  - Feature toggles for analyze/publish/keep/remove are modeled via `FeaturesConfig` and `/api/config/features`.
- **Existing guarantees:**
  - Admin-only actions (`/api/images/{filename}/analyze`, `/publish`, `/keep`, `/remove`) are enforced server-side via `require_auth` (HTTP auth when configured) and `require_admin` (when admin is configured).
  - CLI workflows and orchestrator behavior are unchanged by web-admin work.
- **New assumptions for this change:**
  - `AUTO_VIEW` is provided via `.env` / Heroku config vars, not INI.
  - **Default** for `AUTO_VIEW` is `false` (images private-by-default).
  - When `AUTO_VIEW=false`, images should only be retrievable once the user is in admin mode; admin mode itself continues to require `web_admin_pw`.
  - If admin mode is not configured (no `web_admin_pw`), running with `AUTO_VIEW=false` is considered a misconfiguration, and the safest behavior is to refuse image viewing with a clear error.

## 3. Requirements

### 3.1 Functional Requirements

- **FR1: Env flag and config wiring**
  - Add an `AUTO_VIEW` environment flag, parsed using existing boolean parsing conventions (`parse_bool_env`).
  - Surface this flag as a typed boolean on a config model (chosen: `FeaturesConfig.auto_view_enabled`).
  - Expose `auto_view_enabled` via `/api/config/features` for frontend consumption.

- **FR2: Backend enforcement for random image**
  - When `AUTO_VIEW=false` (i.e., `auto_view_enabled` is `False`):
    - `GET /api/images/random` must **not** return images to non-admin callers.
    - If admin mode is configured (`is_admin_configured()` is true), the endpoint must call `require_admin(request)` before executing the random image logic.
    - If admin mode is **not** configured, the endpoint should return a `503 Service Unavailable` with a safe, generic error (e.g., “Image viewing requires admin mode but admin is not configured.”).
  - When `AUTO_VIEW=true` (i.e., `auto_view_enabled` is `True`):
    - `GET /api/images/random` should behave as it does today, subject only to any existing HTTP auth configuration (which currently applies only to mutating endpoints).

- **FR3: Frontend behavior and messaging**
  - On page load, the UI must fetch `/api/config/features` and store `auto_view_enabled` alongside existing feature flags.
  - When `auto_view_enabled` is `False` and the user is **not** in admin mode:
    - The “Next image” button should either be disabled or produce a clear, non-technical message that admin mode is required to view images (no repeated failing calls).
    - The initial page state must not auto-load an image (no call to `/api/images/random` that succeeds) until admin login has occurred.
  - When `auto_view_enabled` is `True`:
    - The “Next image” button should remain available for non-admin users, and the UI behavior for random image loading should remain unchanged (subject to backend errors).
  - When admin login succeeds (admin mode active), `Next image` should work in both modes.

- **FR4: Backward compatibility**
  - Deploying this change without setting `AUTO_VIEW` must:
    - Behave as `AUTO_VIEW=false` (private-by-default).
    - Leave existing analyze/publish/keep/remove + admin behavior unchanged.
    - Keep existing tests for admin visibility, responsive layout, and feature toggles green.

### 3.2 Non-Functional Requirements

- **Security & privacy:**
  - Fail closed: if `AUTO_VIEW=false` and admin is not configured, image viewing must not silently fall back to anonymous access.
  - The value of `AUTO_VIEW` must never be logged; logs may only record that auto-view is enabled/disabled in high-level structured events if necessary.
  - Existing admin and HTTP auth mechanisms remain authoritative for mutating actions.
- **Performance:**
  - Adding the `auto_view_enabled` check must be O(1) and negligible compared to Dropbox/OpenAI calls.
  - `/api/config/features` remains a cheap, in-memory config read.
- **UX:**
  - Messages for blocked viewing (in private mode when logged out) must be human-readable (e.g., “Admin mode required to view images.”).
  - No additional JS frameworks or build pipelines are introduced.

## 4. Architecture & Design (Delta)

### 4.1 Config & Flags

- **Model change:**
  - Extend `FeaturesConfig` in `publisher_v2.config.schema` with:
    - `auto_view_enabled: bool = Field(default=False, description="Allow random images to be viewed without admin login in the web UI")`
- **Loader change:**
  - In `publisher_v2.config.loader.load_application_config`, construct `FeaturesConfig` with:
    - `auto_view_enabled=parse_bool_env(os.environ.get("AUTO_VIEW"), False, var_name="AUTO_VIEW")`
  - This keeps all flag parsing centralized and reuses existing semantics (truthy/falsey strings).
- **API surface:**
  - Extend `/api/config/features` in `publisher_v2.web.app` to include:
    - `"auto_view_enabled": features.auto_view_enabled`

### 4.2 Backend Endpoint Behavior

- **Affected endpoint:** `api_get_random_image` in `publisher_v2.web.app`.
- **New logic (simplified):**

  - At the top of the handler, before calling the service:
    - Read `features = service.config.features`.
    - If `not features.auto_view_enabled`:
      - If `is_admin_configured()` is `False`:
        - Log a structured event (e.g., `web_random_image_admin_required_but_unconfigured`) and raise `HTTPException(503, "Image viewing requires admin mode but admin is not configured")`.
      - Else:
        - Call `require_admin(request)`; this enforces `pv2_admin` cookie and TTL.
  - After this check passes, proceed with the existing logic (Dropbox image selection, sidecar parsing, hashing, logging).
- **Rationale:**
  - Keeps the guard close to the endpoint, where admin and auth context are already available.
  - Ensures API-level enforcement even if a client ignores or mis-implements the UI logic.

### 4.3 Frontend Template & JS

- **Template:** `publisher_v2/web/templates/index.html`.
- **State additions:**
  - Extend `featureConfig` default to include:
    - `auto_view_enabled: false`
  - Wire `auto_view_enabled` into `fetchFeatureConfig()` so it reads the value from `/api/config/features` when present, defaulting to `false` if missing (for compatibility).
- **Behavior changes:**
  - Add a small helper to compute whether the Next button should be enabled:
    - Enabled if:
      - `!disabled` (no in-flight request), and
      - (`isAdmin` is `true` **or** `featureConfig.auto_view_enabled` is `true`).
  - Update `disableButtons()` and `updateAdminUI()` to:
    - Respect `auto_view_enabled` when setting `btnNext.disabled`.
    - Optionally use the existing `env-indicator` span to show “Private mode” vs “Viewer mode”.
  - Update `apiGetRandom()` to:
    - Early-return with a clear message if `!isAdmin && !featureConfig.auto_view_enabled`, without calling the backend:
      - e.g., `setActivity("Admin mode required to view images.");`
    - Preserve existing success/failure handling and admin-only details behavior when the guard passes.
  - Ensure initial load sequence:
    - Fetches feature config.
    - Refreshes admin status.
    - Only attempts `apiGetRandom()` when either `auto_view_enabled` is `true` or admin is already active; otherwise, shows a “Ready. Admin mode required to view images.” style message.

## 5. Error Handling & Edge Cases

- **AUTO_VIEW=false, admin not configured:**
  - Backend (`/api/images/random`) returns `503 Service Unavailable` with a generic message.
  - UI should surface this as a clear status line and keep the image empty; subsequent Next clicks should not spam the endpoint.
- **AUTO_VIEW=false, admin cookie missing/expired:**
  - Backend raises `403` via `require_admin`.
  - UI treats this similar to existing admin expiry behavior:
    - Clears `isAdmin` state.
    - Shows “Admin session expired, please log in again.” or similar.
- **AUTO_VIEW=true:**
  - Behavior matches current implementation (aside from minor UI status text updates), with admin still required for analysis/publish/keep/remove.
- **Mixed with HTTP auth:**
  - AUTO_VIEW does not modify `require_auth` behavior; if HTTP auth is configured to protect POST endpoints, it continues to do so.
  - GET `/api/images/random` remains unauthenticated at HTTP level but may be admin-gated by AUTO_VIEW; this is consistent with existing separation between HTTP auth and UI-level admin mode.

## 6. Testing Strategy

- **Unit / small integration tests (web & config):**
  - Extend or add tests in `publisher_v2/tests/web/` to verify:
    - `FeaturesConfig.auto_view_enabled` defaults to `False`.
    - `load_application_config` correctly parses `AUTO_VIEW` truthy/falsey strings.
    - `/api/config/features` includes an `auto_view_enabled` boolean key.
- **Web integration tests (`publisher_v2/tests/web_integration/`):**
  - New tests in a file like `test_web_auto_view.py`:
    - `test_random_image_requires_admin_when_auto_view_disabled_and_admin_configured`:
      - Set `AUTO_VIEW=false`, configure `web_admin_pw`, call `/api/images/random` without admin cookie → expect 403.
    - `test_random_image_allows_admin_when_auto_view_disabled`:
      - With `AUTO_VIEW=false` and valid admin login, `/api/images/random` returns 200 and image payload.
    - `test_random_image_unavailable_when_auto_view_disabled_and_admin_unconfigured`:
      - `AUTO_VIEW=false`, no `web_admin_pw` → `/api/images/random` returns 503.
    - `test_random_image_open_when_auto_view_enabled`:
      - `AUTO_VIEW=true` and no admin cookie → `/api/images/random` returns 200 (given mock image).
- **Frontend behavior tests:**
  - Extend existing responsive/admin visibility tests (e.g., `test_web_admin_visibility.py`, `test_web_index_responsive.py`) or add focused assertions to ensure:
    - When rendered with `auto_view_enabled=false` and no admin, “Next image” is disabled or produces the “Admin mode required to view images.” message.
    - When `auto_view_enabled=true`, initial auto-load and Next behavior remain unchanged for non-admin users.
- **Manual checks (staging/Heroku):**
  - Scenario 1: `AUTO_VIEW=false`, `web_admin_pw` set:
    - Open `/` → no image; Next indicates admin required.
    - Log in as admin → Next loads images as normal.
  - Scenario 2: `AUTO_VIEW=true`:
    - Open `/` → image loads as today; admin-only controls still gated.
  - Scenario 3: `AUTO_VIEW=false`, no `web_admin_pw`:
    - Verify `/api/images/random` returns error and UI surfaces a clear message; document this as “unsupported configuration”.

## 7. Work Plan (Scoped)

- **Task 1:** Extend `FeaturesConfig` and `load_application_config` to support `AUTO_VIEW` (`auto_view_enabled`) with default `False`.
- **Task 2:** Update `/api/config/features` response to include `auto_view_enabled`.
- **Task 3:** Update `api_get_random_image` to enforce `AUTO_VIEW` rules with `require_admin` and `is_admin_configured`, returning `503` when misconfigured.
- **Task 4:** Update `index.html` JavaScript to:
  - Load `auto_view_enabled` from `/api/config/features`.
  - Gate the initial image load and Next button behavior on admin state and `auto_view_enabled`.
  - Add clear user-facing status messages for blocked viewing and mode.
- **Task 5:** Add/extend tests covering config parsing, features endpoint, random image endpoint behavior under different configurations, and basic UI/admin visibility expectations.
- **Task 6:** Update relevant documentation under `docs_v2/08_Epics/08_04_ChangeRequests/005` and, if needed, configuration docs to mention `AUTO_VIEW` semantics and defaults.

## 8. Open Questions

- Should `AUTO_VIEW` ever be overridden by an INI-level setting (e.g., `[web] auto_view = true`), or should it remain purely environment-driven for simplicity? — **Proposed answer:** keep it environment-only for MVP; add INI support later if needed.
- Should `AUTO_VIEW` also affect any future thumbnail or list endpoints (e.g., an image grid) if/when they are added? — **Proposed answer:** yes, conceptually `AUTO_VIEW` governs visibility of image content in general; this should be documented now and enforced for future endpoints in follow-up changes.


