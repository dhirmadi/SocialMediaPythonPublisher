# Implementation Story: 02_web_integration

This story covers the web integration defined in 010_02_plan.yaml.

## Context
This story exposes the backend curation capabilities to the Web UI, adding admin controls and API endpoints.

## Plan Execution

### 1. Web Service & API
*   **Models**: Added `CurationResponse` to `publisher_v2/web/models.py`.
*   **Service Layer**: Extended `WebImageService` in `publisher_v2/web/service.py`:
    *   `keep_image` and `remove_image` delegate to the orchestrator.
    *   Raises `PermissionError` if features are disabled.
*   **Endpoints**: Added FastAPI endpoints in `publisher_v2/web/app.py`:
    *   `POST /api/images/{filename}/keep`
    *   `POST /api/images/{filename}/remove`
    *   Both are protected by `require_admin`.
    *   Extended `GET /api/config/features` to expose curation feature flags.

### 2. Web UI
*   **HTML Template**: Updated `publisher_v2/web/templates/index.html`:
    *   Added "Keep" and "Remove" buttons to the admin controls.
*   **JavaScript**:
    *   Updated `featureConfig` and `updateAdminUI` to manage button visibility.
    *   Implemented `apiKeep` and `apiRemove` to call the endpoints and auto-advance to the next image on success.

### 3. Documentation
*   **Configuration**: Updated `docs_v2/05_Configuration/CONFIGURATION.md` to document the new INI keys, environment variables, and feature flags.

## Verification
*   **Tests**:
    *   `test_web_keep_remove_service.py`: Verifies service layer delegation and error handling.
    *   `test_web_keep_remove_endpoints.py`: Verifies API security (admin auth) and response codes.
*   **UX**: Verified that buttons appear only for admins and that the curation flow is smooth (immediate feedback + next image).

