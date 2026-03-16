# PUB-005: Web Interface MVP

| Field | Value |
|-------|-------|
| **ID** | PUB-005 |
| **Category** | Web UI |
| **Priority** | INF |
| **Effort** | L |
| **Status** | Done |
| **Dependencies** | — |

## Problem

Today the system can only be operated via a CLI command on a machine with terminal access, which is inconvenient when the user wants to run workflows from a mobile device. This friction makes it harder to casually preview images, trigger AI analysis/caption generation, and publish content while away from the development machine. The existing architecture already encapsulates image selection, AI processing, sidecar creation, and publishing, but there is no thin, easy-to-use web layer exposing those capabilities.

## Desired Outcome

A minimal web UI accessible from a phone that can show a random image from the configured Dropbox folder, trigger AI analysis and caption/sd_caption generation, and trigger publishing to configured channels. The solution reuses existing V2 orchestration, AI, storage, and sidecar mechanisms, deploys as a single Heroku web app, and keeps the architecture simple and extensible for future features.

## Scope

- Single-page, mobile-friendly web UI with image viewer and buttons for "Next image", "Analyze & caption", and "Publish"
- FastAPI/Starlette web server integrated into `publisher_v2` without altering CLI behavior
- Reuse of `WorkflowOrchestrator`, `DropboxStorage`, `AIService`, publishers, and sidecar builders
- Optional lightweight access control (basic auth or shared token) for admin actions
- Preview/dry-run modes respected; no external publishing or archiving in those modes
- Deployable as single Heroku web dyno via `Procfile` and `uvicorn`
- No new databases; state in Dropbox and sidecar files only

## Acceptance Criteria

- AC1: Given the app is deployed with valid config, when I open `/`, I see a page with image display and buttons for "Next image", "Analyze & caption", and "Publish"
- AC2: Given eligible images exist, when I click "Next image", the backend selects a random image and the UI updates
- AC3: Given an image without AI sidecar, when I click "Analyze & caption", the backend runs AI analysis and caption generation, writes the sidecar, and the UI displays the caption
- AC4: Given an image with an existing sidecar, when I click "Analyze & caption", the sidecar is updated and the UI reflects the new caption
- AC5: Given valid platform config, when I click "Publish", the backend invokes publishers, archives on success, and the UI shows success/failure per platform
- AC6: Given preview/dry mode, web UI actions perform no external publishing or archiving
- AC7: Given optional protection is configured, unauthenticated users cannot trigger analysis/publish; authenticated users can use all admin actions
- AC8: Given any error during operations, the UI shows a clear error message and the server logs structured errors without exposing secrets

## Implementation Notes

- Web framework: FastAPI/Starlette with ASGI via uvicorn
- Endpoints: `/` (index), `/api/images/random`, `/api/images/{filename}/analyze`, `/api/images/{filename}/publish`
- Web layer calls into `WorkflowOrchestrator` and existing services; no logic duplication
- Structured logs: `web_next_image`, `web_analyze`, `web_caption`, `web_publish` with correlation IDs
- Config via env vars and INI; no MongoDB, streams, or multi-tenant in MVP

## Related

- [Original feature doc](../../08_Epics/002_web_admin_curation_ux/005_web_interface_mvp/005_feature.md) — full historical detail
