# Web Interface MVP — Implementation Notes

## Overview

This document describes the concrete implementation of feature **005 — Web Interface MVP**.
The goal is to expose a minimal web UI on top of Publisher V2 that allows:

- Viewing a random image from the configured Dropbox folder.
- Triggering AI analysis and caption/sd_caption generation.
- Publishing the image using the existing publishers.

The implementation is fully backward compatible with the existing CLI workflow.

## Key Components

- `publisher_v2.web.app` — FastAPI application, routes, startup logging, HTML rendering.
- `publisher_v2.web.service.WebImageService` — Thin orchestration layer that delegates to:
  - `DropboxStorage`
  - `AIService` (Vision + Caption)
  - `WorkflowOrchestrator`
- `publisher_v2.web.models` — Pydantic request/response models.
- `publisher_v2.web.auth` — Simple bearer/basic auth based on `WEB_AUTH_*` env vars.
- `publisher_v2.web.sidecar_parser` — Parser for existing sidecar `.txt` files.
- `publisher_v2.web.templates/index.html` — Single-page HTML UI with minimal JS.

## Configuration

- Dependencies added in `pyproject.toml`:
  - `fastapi`
  - `uvicorn`
  - `jinja2`
- New config model in `config/schema.py`:
  - `WebConfig` added and wired into `ApplicationConfig` as `web`, with defaults.
- Runtime configuration:
  - `CONFIG_PATH` (required): path to existing INI config, e.g. `configfiles/fetlife.ini`.
  - `ENV_PATH` (optional): path to `.env` file.
  - `WEB_AUTH_TOKEN` (optional): bearer token for protected endpoints.
  - `WEB_AUTH_USER` / `WEB_AUTH_PASS` (optional): basic auth credentials.
  - `WEB_DEBUG` (optional): enables DEBUG logging when set to truthy value.
  - `web_admin_pw` (optional): admin password used by the Web UI to unlock admin-only controls.
  - `WEB_ADMIN_COOKIE_TTL_SECONDS` (optional): TTL for the admin cookie in seconds (default ~1h).

## HTTP Endpoints

- `GET /`
  - Renders `index.html`.
- `GET /api/images/random`
  - Returns random image from `dropbox.image_folder` with:
    - `filename`, `temp_url`, optional `sha256`.
    - Sidecar-derived `caption`, `sd_caption`, and metadata (if present).
  - 404 when no images are found.
- `POST /api/images/{filename}/analyze`
  - Protected by auth (if enabled).
  - Runs AI analysis + caption/sd_caption generation.
  - Writes/overwrites sidecar via `DropboxStorage.write_sidecar_text`.
  - Returns `AnalysisResponse`.
- `POST /api/images/{filename}/publish`
  - Protected by auth (if enabled).
  - Delegates to `WorkflowOrchestrator.execute(select_filename=filename, dry_publish=False, preview_mode=False)`.
  - Returns per-platform result and archive flag as `PublishResponse`.
- `POST /api/admin/login`
  - Verifies the admin password from `web_admin_pw` and, on success, issues a short-lived admin cookie.
  - Returns `{ "admin": true }` on success; `401` or `503` on failure/unconfigured state.
- `GET /api/admin/status`
  - Returns `{ "admin": true|false }` based on the presence of the admin cookie.
- `GET /health`
  - Returns `{ "status": "ok" }`.

## Deployment

- `Procfile`:
  - `web: uvicorn publisher_v2.web.app:app --host 0.0.0.0 --port $PORT`
- Heroku configuration (example):

```bash
heroku config:set CONFIG_PATH=configfiles/fetlife.ini
heroku config:set DROPBOX_APP_KEY=...
heroku config:set DROPBOX_APP_SECRET=...
heroku config:set DROPBOX_REFRESH_TOKEN=...
heroku config:set OPENAI_API_KEY=...
heroku config:set WEB_AUTH_TOKEN=some-long-secret
```

## Testing

- Unit tests:
  - `publisher_v2/tests/web/test_sidecar_parser.py`
  - `publisher_v2/tests/web/test_web_auth.py`
  - `publisher_v2/tests/web/test_web_service.py`
- Integration tests:
  - `publisher_v2/tests/web_integration/test_web_endpoints.py`
  - `publisher_v2/tests/web_integration/test_web_auth_integration.py`
- E2E harness:
  - `publisher_v2/tests/test_e2e_web_interface_mvp.py` (skipped unless `CONFIG_PATH` points to a real config).


