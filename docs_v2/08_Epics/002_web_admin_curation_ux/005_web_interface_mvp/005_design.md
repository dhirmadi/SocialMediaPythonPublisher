# Web Interface MVP — Feature Design

**Feature ID:** 005  
**Feature Name:** web-interface-mvp  
**Design Version:** 1.0  
**Date:** 2025-11-19  
**Status:** Design Review  
**Author:** Architecture Team  

---

## 1. Summary

### Problem
The Social Media Publisher V2 currently operates exclusively via CLI, requiring terminal access and preventing mobile-based operation. This creates friction for casual workflows like previewing images, triggering AI analysis, or publishing content while away from a development machine.

### Goals
1. Provide a minimal, phone-accessible web UI for image viewing, AI processing, and publishing.
2. Reuse 100% of existing V2 orchestration, AI, storage, and publishing logic without duplication.
3. Deploy as a single Heroku web dyno with no new persistent data stores (Dropbox + sidecars remain source of truth).
4. Maintain full backward compatibility with CLI workflows.
5. Keep architecture simple and extensible for future enhancements (streams, MongoDB, richer roles).

### Non-Goals
- Multi-stream/folder concepts (single configured folder only).
- MongoDB or any new persistent database.
- Full user management or complex RBAC (single operator + optional simple auth).
- Public gallery or viewer accounts.
- Breaking or replacing existing CLI behavior.

---

## 2. Context & Assumptions

### Current State
- **Architecture:** Layered monolith with CLI entrypoint (`app.py`).
- **Core components:**
  - `WorkflowOrchestrator`: select → analyze → caption → publish → archive.
  - `DropboxStorage`: list, download, temp link, archive, sidecar operations.
  - `AIService` (VisionAnalyzerOpenAI + CaptionGeneratorOpenAI).
  - Publishers: Telegram, Email, Instagram (pluggable).
- **Configuration:** INI file + `.env` for secrets; Pydantic validation.
- **State management:** SHA256 dedup via `posted_hashes.txt`; sidecar `.txt` files for metadata.
- **Deployment:** Local or server with **uv**; no existing web layer (Poetry also supported).

### Constraints
1. Python 3.9–3.12 compatibility (per `pyproject.toml`).
2. No new databases; Dropbox remains authoritative.
3. Async patterns must be preserved (existing code uses `asyncio.to_thread` for blocking SDK calls).
4. Heroku deployment target (single web dyno).
5. Existing CLI must remain fully functional and unchanged.

### Dependencies
- **External:** Dropbox SDK, OpenAI API, Telegram Bot API, SMTP (Gmail), Instagram (instagrapi).
- **Internal:** All existing V2 services and utilities.
- **New (web layer only):** FastAPI (recommended), `uvicorn` (ASGI server), optional `python-multipart` for file uploads (future).

### Assumptions
1. Single operator use case for MVP; multi-user is deferred.
2. Heroku provides HTTPS by default; no additional TLS config needed.
3. Web UI sessions are stateless; no server-side session store required.
4. Config INI path is provided via environment variable (`CONFIG_PATH`).
5. Simple protection (HTTP Basic Auth or shared token) is sufficient for MVP.

---

## 3. Requirements

### Functional Requirements

**FR1: Web UI Root Endpoint**
- Serve a single-page interface at `/` with:
  - Image display area.
  - Buttons: "Next Image", "Analyze & Caption", "Publish".
  - Caption/metadata display area.

**FR2: Random Image Selection**
- `GET /api/images/random`:
  - Lists images from configured Dropbox folder.
  - Selects random image (with optional dedup logic).
  - Returns image metadata + temporary Dropbox URL.
  - Attempts to read existing sidecar; returns parsed caption/sd_caption if present.

**FR3: AI Analysis & Caption Generation**
- `POST /api/images/{filename}/analyze`:
  - Runs existing AI analysis + caption generation (reusing `AIService`).
  - Writes/overwrites sidecar file via `DropboxStorage.write_sidecar_text`.
  - Returns `ImageAnalysis` + generated caption.

**FR4: Publishing**
- `POST /api/images/{filename}/publish`:
  - Invokes existing `WorkflowOrchestrator.execute` or equivalent publishing logic.
  - Returns per-platform `PublishResult` and archive status.
  - Respects dry/preview/debug modes from config.

**FR5: Sidecar Reading**
- Internal utility to parse existing `.txt` sidecars and extract:
  - `sd_caption` (first line or section).
  - Metadata JSON block (if present).

**FR6: Authentication (Optional)**
- Simple protection via HTTP Basic Auth or Bearer token.
- Env var `WEB_AUTH_TOKEN` or `WEB_AUTH_USER`/`WEB_AUTH_PASS`.
- Middleware checks credentials before allowing `/api/images/*/analyze` or `*/publish`.

**FR7: Health Check**
- `GET /health`:
  - Returns `{ "status": "ok" }` for monitoring.

**FR8: CLI Unchanged**
- Existing `app.py` CLI entrypoint remains independent and fully functional.

### Non-Functional Requirements

**NFR1: Performance**
- P95 latency targets:
  - `/api/images/random`: < 5s.
  - `/api/images/{filename}/analyze`: < 20s.
  - `/api/images/{filename}/publish`: < 30s.

**NFR2: Security**
- No secrets in responses or logs.
- HTTPS enforced via Heroku.
- Optional Basic Auth or token-based protection.

**NFR3: Observability**
- Structured logs for all web actions (`web_next_image`, `web_analyze`, `web_publish`).
- Correlation IDs for request tracing.
- Reuse existing `utils.logging.log_json`.

**NFR4: Scalability**
- Single dyno sufficient for single-user MVP.
- Stateless design allows horizontal scaling if needed later.

**NFR5: Maintainability**
- Web layer integrated into `publisher_v2` package as new module (`web/`).
- No code duplication; all business logic via existing services.

**NFR6: Accessibility**
- Mobile-friendly viewport.
- Touch-friendly buttons.
- Alt text for images.

---

## 4. Architecture & Design

### Proposed Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Heroku Web Dyno                      │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              FastAPI Web Application                 │   │
│  │                                                       │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐          │   │
│  │  │   GET /  │  │ GET /api │  │ POST /api│          │   │
│  │  │ (UI HTML)│  │ /images/ │  │ /images/ │          │   │
│  │  │          │  │  random  │  │ {}/analyze│         │   │
│  │  └──────────┘  └──────────┘  └──────────┘          │   │
│  │                      │              │                │   │
│  │                      ▼              ▼                │   │
│  │            ┌──────────────────────────────┐        │   │
│  │            │   WebImageService (new)      │        │   │
│  │            │  - random_image()            │        │   │
│  │            │  - analyze_and_caption()     │        │   │
│  │            │  - publish_image()           │        │   │
│  │            └──────────────────────────────┘        │   │
│  │                      │                              │   │
│  │                      ▼                              │   │
│  │     ┌────────────────────────────────────────┐    │   │
│  │     │  Existing V2 Services (reused)          │    │   │
│  │     │  - WorkflowOrchestrator                 │    │   │
│  │     │  - DropboxStorage                       │    │   │
│  │     │  - AIService (Analyzer + Generator)     │    │   │
│  │     │  - Publishers (Telegram/Email/IG)       │    │   │
│  │     │  - SidecarBuilder, StateManager         │    │   │
│  │     └────────────────────────────────────────┘    │   │
│  │                      │                              │   │
│  └──────────────────────┼──────────────────────────────┘   │
│                         ▼                                   │
└────────────────────────┼────────────────────────────────────┘
                         │
         ┌───────────────┼───────────────┐
         │               │               │
         ▼               ▼               ▼
    ┌─────────┐   ┌──────────┐   ┌──────────┐
    │ Dropbox │   │  OpenAI  │   │Publishers│
    │ (images,│   │  (GPT-4o)│   │(Telegram,│
    │sidecars)│   │          │   │Email, IG)│
    └─────────┘   └──────────┘   └──────────┘
```

### Components & Responsibilities

#### New Components

**1. `publisher_v2.web.app` (FastAPI application)**
- Root module for web layer.
- Defines FastAPI app instance, routes, middleware.
- Lifespan context manager for config loading and service initialization.

**2. `publisher_v2.web.routes` (API endpoints)**
- `GET /`: Serve HTML UI.
- `GET /api/images/random`: Random image selection + sidecar read.
- `POST /api/images/{filename}/analyze`: Trigger analysis + caption + sidecar write.
- `POST /api/images/{filename}/publish`: Trigger publishing + archive.
- `GET /health`: Health check.

**3. `publisher_v2.web.service` (WebImageService)**
- Thin orchestration layer between HTTP handlers and existing services.
- Methods:
  - `async def get_random_image() -> ImageResponse`
  - `async def analyze_and_caption(filename: str) -> AnalysisResponse`
  - `async def publish_image(filename: str, platforms: list[str]) -> PublishResponse`
- Holds references to `DropboxStorage`, `AIService`, `WorkflowOrchestrator`, config.

**4. `publisher_v2.web.models` (Pydantic request/response schemas)**
- `ImageResponse`, `AnalysisResponse`, `PublishResponse`, `ErrorResponse`.

**5. `publisher_v2.web.auth` (Optional auth middleware)**
- Basic Auth or Bearer token validation.

**6. `publisher_v2.web.templates` (HTML templates)**
- Single `index.html` with embedded CSS/JS (or static files).

**7. `publisher_v2.web.sidecar_parser` (Utility)**
- Parse `.txt` sidecar format into structured dict.

#### Unchanged Components (Reused)

- `config.loader`, `config.schema`: Load and validate config (add `WebConfig` section).
- `core.workflow.WorkflowOrchestrator`: Reused for publish flow.
- `services.storage.DropboxStorage`: All storage operations.
- `services.ai.AIService`: Analysis and caption generation.
- `services.publishers.*`: All existing publishers.
- `utils.*`: Logging, state, captions, images, rate limiting.

### Data Model / Schemas

#### Before (CLI-only)
- No web-specific models.
- CLI uses `WorkflowResult` dataclass.

#### After (Web + CLI)

**New: `WebConfig` (added to `config.schema.ApplicationConfig`)**

```python
class WebConfig(BaseModel):
    enabled: bool = Field(default=False, description="Enable web interface")
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    auth_enabled: bool = Field(default=True)
    auth_token: Optional[str] = Field(default=None, description="Bearer token for API auth")
    auth_user: Optional[str] = Field(default=None, description="Basic auth username")
    auth_pass: Optional[str] = Field(default=None, description="Basic auth password")
```

**New: Web API Schemas (`publisher_v2.web.models`)**

```python
from pydantic import BaseModel
from typing import Optional

class ImageResponse(BaseModel):
    filename: str
    temp_url: str
    sha256: Optional[str] = None
    caption: Optional[str] = None
    sd_caption: Optional[str] = None
    metadata: Optional[dict] = None
    has_sidecar: bool

class AnalysisResponse(BaseModel):
    filename: str
    description: str
    mood: str
    tags: list[str]
    nsfw: bool
    caption: str
    sd_caption: Optional[str] = None
    sidecar_written: bool

class PublishResponse(BaseModel):
    filename: str
    results: dict[str, dict]  # platform -> {success, post_id, error}
    archived: bool
    any_success: bool

class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
```

**Sidecar Format (unchanged)**
- First line: `sd_caption` text.
- Blank line.
- JSON metadata block (Phase 1 + optional Phase 2).

### API/Contracts

#### `GET /`
- Returns: HTML page (UI).

#### `GET /api/images/random`
- **Response 200:**
  ```json
  {
    "filename": "image001.jpg",
    "temp_url": "https://dl.dropboxusercontent.com/...",
    "sha256": "abc123...",
    "caption": "Existing caption if sidecar present",
    "sd_caption": "Existing SD caption if sidecar present",
    "metadata": { "created": "2025-11-19T...", ... },
    "has_sidecar": true
  }
  ```
- **Response 404:** `{ "error": "No images found" }`
- **Response 500:** `{ "error": "Dropbox error", "detail": "..." }`

#### `POST /api/images/{filename}/analyze`
- **Request:** None (filename in path).
- **Response 200:**
  ```json
  {
    "filename": "image001.jpg",
    "description": "A fine-art portrait...",
    "mood": "contemplative",
    "tags": ["portrait", "fine_art", ...],
    "nsfw": false,
    "caption": "Generated social media caption...",
    "sd_caption": "Fine-art portrait, soft lighting...",
    "sidecar_written": true
  }
  ```
- **Response 404:** `{ "error": "Image not found" }`
- **Response 500:** `{ "error": "AI analysis failed", "detail": "..." }`

#### `POST /api/images/{filename}/publish`
- **Request (optional body):**
  ```json
  {
    "platforms": ["telegram", "email"]  // Optional; defaults to all enabled
  }
  ```
- **Response 200:**
  ```json
  {
    "filename": "image001.jpg",
    "results": {
      "telegram": { "success": true, "post_id": "123" },
      "email": { "success": true, "post_id": null }
    },
    "archived": true,
    "any_success": true
  }
  ```
- **Response 404:** `{ "error": "Image not found" }`
- **Response 500:** `{ "error": "Publishing failed", "detail": "..." }`

#### `GET /health`
- **Response 200:** `{ "status": "ok" }`

#### Authentication
- If `web.auth_enabled=true`:
  - All POST endpoints require:
    - **Bearer token:** `Authorization: Bearer <token>` (if `auth_token` set), OR
    - **Basic Auth:** `Authorization: Basic <base64(user:pass)>` (if `auth_user`/`auth_pass` set).
  - GET endpoints (including `/api/images/random`) are optionally protected (config flag `auth_required_for_read`).

### Error Handling & Retries

- **Dropbox errors:** Existing `StorageError` caught by web handlers → 500 with sanitized message.
- **AI errors:** Existing `AIServiceError` caught → 500 with sanitized message.
- **Publishing errors:** Per-platform failures captured in `PublishResult`; returned in response (not thrown).
- **Retries:** Existing `tenacity` decorators in services remain; web layer does not add extra retries.
- **Logging:** All errors logged via `log_json` with correlation IDs.

### Security, Privacy, Compliance

1. **Secrets:**
   - Never exposed in API responses or logs.
   - Config loaded from env vars (`DROPBOX_REFRESH_TOKEN`, `OPENAI_API_KEY`, etc.).

2. **Authentication:**
   - Optional Basic Auth or Bearer token (env-configured).
   - Heroku enforces HTTPS; no plain-text credentials over wire.

3. **Authorization:**
   - MVP assumes single operator; no per-user permissions.
   - Future: extend to role-based checks (admin vs. viewer).

4. **Content moderation:**
   - Existing PG-13 fine-art prompts remain unchanged.
   - NSFW flag from AI analysis logged but not enforced in MVP.

5. **CORS:**
   - Not required in MVP (UI served from same origin).
   - If SPA hosted elsewhere later: add `CORSMiddleware` with allowed origins.

6. **Rate limiting:**
   - Existing `AsyncRateLimiter` in `AIService` remains active.
   - No additional web-layer rate limiting in MVP (single user).

---

## 5. Detailed Flow

### Flow 1: User Opens Web UI

```
1. User navigates to https://<app>.herokuapp.com/
2. FastAPI serves GET / → returns index.html
3. HTML loads, displays "Loading..." placeholder
4. JavaScript calls GET /api/images/random
5. Backend:
   a. Loads config from env
   b. Calls DropboxStorage.list_images(folder)
   c. Selects random image (shuffle, pick first)
   d. Calls DropboxStorage.get_temporary_link(folder, filename)
   e. Attempts to read sidecar via DropboxStorage.download_image(folder, filename.replace(ext, '.txt'))
      - If exists: parse and extract caption/sd_caption/metadata
      - If not exists: return has_sidecar=false
   f. Compute SHA256 (optional, if image downloaded for dedup)
   g. Return ImageResponse
6. Frontend updates UI with image, caption (if any), and enables public controls; admin-only controls remain hidden until admin login
```

### Flow 2: User Clicks "Analyze & Caption"

```
1. JavaScript calls POST /api/images/{filename}/analyze
2. Backend:
   a. Calls DropboxStorage.get_temporary_link(folder, filename)
   b. Calls AIService.analyzer.analyze(temp_link) → ImageAnalysis
   c. Builds CaptionSpec (reusing existing logic from WorkflowOrchestrator)
   d. Calls AIService.generator.generate_with_sd(analysis, spec) → {caption, sd_caption}
   e. Builds sidecar content via utils.captions.build_caption_sidecar(sd_caption, metadata)
   f. Calls DropboxStorage.write_sidecar_text(folder, filename, content)
   g. Logs structured event: web_analyze_complete
   h. Return AnalysisResponse
3. Frontend updates caption display area; shows success message
```

### Flow 3: User Clicks "Publish"

```
1. JavaScript calls POST /api/images/{filename}/publish
2. Backend:
   a. Option 1: Call WorkflowOrchestrator.execute(select_filename=filename, dry_publish=False)
      - Reuses full workflow (analysis skipped if sidecar exists, publish + archive)
   b. Option 2: Direct orchestration:
      - Download image to temp file
      - Load sidecar to get caption
      - Call publishers in parallel via asyncio.gather
      - Archive if any_success
   c. Logs structured event: web_publish_complete
   d. Return PublishResponse
3. Frontend displays per-platform results; shows "Archived" if true
```

### Edge Cases

1. **No images in folder:** Return 404 on `/api/images/random`.
2. **Image deleted between random + analyze:** Return 404 on POST.
3. **AI service timeout:** Existing retries exhaust → return 500 with error detail.
4. **Publishing partial failure:** Return 200 with per-platform success/failure in results.
5. **Dyno restart during publish:** Workflow is idempotent (dedup via SHA256); safe to retry.
6. **Sidecar parse error:** Log warning, treat as missing sidecar, proceed.
7. **Auth failure:** Return 401 with `{ "error": "Unauthorized" }`.

---

## 6. Rollout & Ops

### Feature Flags

**Option A: Config-based**
- Add `[web]` section to INI:
  ```ini
  [web]
  enabled = true
  auth_enabled = true
  auth_token = <secret>
  ```

**Option B: Env-based (recommended for Heroku)**
- Environment variables:
  - `WEB_ENABLED=true` (default false; if false, web server does not start)
  - `WEB_AUTH_TOKEN=<secret>`
  - `WEB_AUTH_USER=<user>`
  - `WEB_AUTH_PASS=<pass>`

### Configuration

**Heroku Config Vars:**
```bash
CONFIG_PATH=/app/configfiles/fetlife.ini  # Or inline config if supported
DROPBOX_REFRESH_TOKEN=<secret>
DROPBOX_APP_KEY=<secret>
DROPBOX_APP_SECRET=<secret>
OPENAI_API_KEY=<secret>
TELEGRAM_BOT_TOKEN=<secret>
TELEGRAM_CHANNEL_ID=<id>
WEB_ENABLED=true
WEB_AUTH_TOKEN=<random-secret>
```

**Procfile:**
```
web: uvicorn publisher_v2.web.app:app --host 0.0.0.0 --port $PORT
```

**Optional: CLI still available via `worker` dyno:**
```
worker: uv run python -m publisher_v2.app --config /app/configfiles/fetlife.ini
```

### Migration/Backfill Plan

- **No migration needed:** Existing data (images, sidecars, `posted_hashes.txt`) remain unchanged.
- Backward compatibility: CLI continues to work identically; web is additive.

### Monitoring, Logging, Dashboards, Alerts

**Logging:**
- Structured JSON logs via existing `utils.logging.log_json`.
- New event types:
  - `web_server_start`
  - `web_request` (per endpoint, with correlation_id)
  - `web_random_image`
  - `web_analyze_complete`
  - `web_publish_complete`
  - `web_error` (with exception details, sanitized)

**Metrics (manual tracking via logs for MVP):**
- Count of `/api/images/random` calls.
- Count of `/api/images/{}/analyze` calls.
- Count of `/api/images/{}/publish` calls.
- Success/failure rates per endpoint.

**Dashboards:**
- Heroku Metrics dashboard (dyno CPU/memory).
- Optional: External log aggregator (Papertrail, Loggly) for structured log queries.

**Alerts:**
- Heroku: Alert on dyno crash or sustained high error rate (5xx > 10% over 5 min).
- Optional: Custom alert on `web_error` spike via log aggregator.

### Capacity/Cost Estimates

**Heroku Dyno:**
- Hobby dyno ($7/month) sufficient for MVP (single user, low traffic).
- Standard-1X ($25/month) for production with higher reliability.

**Dropbox API:**
- Existing usage; web adds minimal overhead (temp links are cheap).

**OpenAI API:**
- Same as CLI; cost per analysis/caption unchanged (~$0.01–0.05 per image depending on model).

**Bandwidth:**
- Heroku: Free tier allows modest traffic; image temp links served by Dropbox (no Heroku bandwidth).

---

## 7. Testing Strategy

### Unit Tests

**Target:** `publisher_v2/tests/web/`

1. **`test_web_service.py`:**
   - Mock `DropboxStorage`, `AIService`, `WorkflowOrchestrator`.
   - Test `WebImageService.get_random_image()`:
     - Returns `ImageResponse` with temp_url.
     - Handles no images (raises or returns None).
     - Parses sidecar if present.
   - Test `WebImageService.analyze_and_caption()`:
     - Calls AI services, writes sidecar, returns `AnalysisResponse`.
   - Test `WebImageService.publish_image()`:
     - Calls orchestrator, returns `PublishResponse`.

2. **`test_sidecar_parser.py`:**
   - Parse valid sidecar → extract sd_caption + metadata.
   - Parse sidecar with missing metadata → graceful fallback.
   - Parse invalid sidecar → log warning, return None.

3. **`test_web_auth.py`:**
   - Valid token → pass.
   - Invalid token → 401.
   - Basic auth valid → pass.
   - Basic auth invalid → 401.

### Integration Tests

**Target:** `publisher_v2/tests/web_integration/`

1. **`test_web_endpoints.py`:**
   - Use FastAPI `TestClient`.
   - Mock external dependencies (Dropbox, OpenAI).
   - Test `GET /api/images/random`:
     - Returns 200 with `ImageResponse`.
     - Returns 404 if no images.
   - Test `POST /api/images/{filename}/analyze`:
     - Returns 200 with `AnalysisResponse`.
     - Returns 404 if image not found.
   - Test `POST /api/images/{filename}/publish`:
     - Returns 200 with `PublishResponse`.
     - Handles partial failures gracefully.
   - Test `GET /health`:
     - Returns 200.

2. **`test_web_auth_integration.py`:**
   - Protect endpoints with auth middleware.
   - Valid token → 200.
   - Missing token → 401.

### E2E Tests

**Target:** Manual testing on Heroku staging environment.

1. Deploy to staging Heroku app.
2. Open UI on phone browser.
3. Click "Next Image" → verify image loads, caption shown if sidecar exists.
4. Click "Analyze & Caption" → verify caption generated, displayed, sidecar written (check Dropbox).
5. Click "Publish" → verify platforms receive post, image archived (check Dropbox `/archive`).
6. Test auth: access without token → 401; with valid token → 200.
7. Test error paths: delete image in Dropbox after random selection → 404 on analyze.

### Performance Tests

**Target:** Verify latency targets.

1. Use `locust` or manual timing to measure:
   - `/api/images/random`: P95 < 5s.
   - `/api/images/{filename}/analyze`: P95 < 20s.
   - `/api/images/{filename}/publish`: P95 < 30s.
2. Run with real Dropbox/OpenAI calls (not mocked) in staging.

### Test Cases Mapped to Acceptance Criteria

| Acceptance Criterion | Test Case |
|----------------------|-----------|
| Open root URL → see UI with buttons | E2E: manual browser test |
| Click "Next image" → UI updates with random image | Integration: `test_web_endpoints.py::test_random_image` |
| Click "Analyze & caption" → AI runs, sidecar written, UI shows caption | Integration: `test_web_endpoints.py::test_analyze` + E2E |
| Sidecar already present → "Analyze" updates it | Integration: test with pre-existing sidecar mock |
| Click "Publish" → publishers invoked, archive on success | Integration: `test_web_endpoints.py::test_publish` + E2E |
| Dry/preview mode → no external actions | Unit: mock orchestrator with `dry_publish=True` |
| Auth enabled → unauthenticated user cannot analyze/publish | Integration: `test_web_auth_integration.py` |
| Error during Dropbox/AI → clear error message in UI | Integration: mock exception, verify `ErrorResponse` |

---

## 8. Risks & Alternatives

### Risks with Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Web layer diverges from CLI behavior | High | Reuse `WorkflowOrchestrator` and services; add integration tests comparing CLI and web outputs |
| Accidental publish without auth | High | Enforce auth by default; require explicit config to disable |
| Heroku dyno sleep (free tier) | Medium | Use Hobby or Standard dyno; document sleep behavior; add wake-up ping if needed |
| Latency on mobile networks | Medium | Provide loading indicators in UI; rely on existing retry logic |
| Sidecar format changes break parser | Low | Version sidecar format; parser handles missing fields gracefully |
| Config drift between CLI and web | Low | Share single `ApplicationConfig`; web adds optional `WebConfig` section |

### Alternatives Considered

**Alternative 1: Separate FastAPI project**
- **Pros:** Clean separation; independent deployment.
- **Cons:** Code duplication; harder to keep CLI and web in sync.
- **Decision:** Rejected; integrated web layer in same repo is simpler and DRYer.

**Alternative 2: Flask instead of FastAPI**
- **Pros:** Simpler, fewer dependencies.
- **Cons:** No built-in async support (needs `quart` or `aiohttp`); less type safety.
- **Decision:** Rejected; FastAPI aligns with existing async patterns and Pydantic models.

**Alternative 3: Server-side rendering (Jinja2 templates) instead of SPA**
- **Pros:** Simpler frontend; no separate build step.
- **Cons:** Less interactive; harder to add rich UI later.
- **Decision:** **Recommended for MVP**; serve single HTML with embedded JS for AJAX calls. Can evolve to SPA later.

**Alternative 4: Add MongoDB for image metadata**
- **Pros:** Faster queries; richer search/filtering.
- **Cons:** Adds operational complexity; overkill for single-folder MVP.
- **Decision:** Rejected for MVP; defer to future feature (streams).

**Alternative 5: Use existing orchestrator as-is vs. new `WebImageService`**
- **Pros (orchestrator):** Maximum reuse; guaranteed identical behavior.
- **Cons (orchestrator):** Orchestrator expects full workflow (select → analyze → publish); web needs granular control.
- **Decision:** Hybrid approach:
  - `/api/images/{}/publish` calls orchestrator with `select_filename` (reuses full flow).
  - `/api/images/random` and `/api/images/{}/analyze` call services directly via thin `WebImageService`.

---

## 9. Work Plan

### Milestones

**M1: Design & Wiring (Week 1)**
- Exit Criteria:
  - Feature design doc approved (this document).
  - FastAPI added to `pyproject.toml` dependencies.
  - Skeleton `publisher_v2/web/` module created with placeholder routes.
  - `Procfile` created for Heroku deployment.
  - Auth strategy decided (env-based token).

**M2: Implementation (Weeks 2–3)**
- Exit Criteria:
  - `WebImageService` implemented with `get_random_image`, `analyze_and_caption`, `publish_image`.
  - Sidecar parser utility implemented.
  - API endpoints implemented and wired to service.
  - HTML UI implemented (single page with embedded CSS/JS).
  - Auth middleware implemented and tested.
  - Unit tests for service and parser (>80% coverage).
  - Integration tests for API endpoints.

**M3: Validation & Deployment (Week 4)**
- Exit Criteria:
  - Heroku staging app deployed and tested.
  - E2E tests on phone browser (iOS/Android).
  - CLI regression tests pass (no behavior changes).
  - Documentation updated:
    - `docs_v2/08_Epics/08_03_Implementation/005_web-interface-mvp.md`.
    - `docs_v2/03_Architecture/ARCHITECTURE.md` (mention web layer).
    - `README.md` (add web deployment instructions).
  - Observability: structured logs verified in Heroku logs.
  - Production deployment to Heroku (with auth enabled).

### Tasks (High-Level)

1. Add FastAPI, uvicorn, python-multipart to `pyproject.toml`.
2. Create `publisher_v2/web/` module structure:
   - `app.py` (FastAPI app, lifespan, routes)
   - `service.py` (`WebImageService`)
   - `models.py` (Pydantic schemas)
   - `auth.py` (middleware)
   - `sidecar_parser.py` (utility)
   - `templates/index.html` (UI)
3. Implement API endpoints (routes).
4. Implement `WebImageService` methods (call existing services).
5. Implement sidecar parser (read `.txt`, extract sd_caption + JSON metadata).
6. Implement auth middleware (Basic Auth or Bearer token).
7. Create HTML UI with AJAX calls to API.
8. Write unit tests (`tests/web/`).
9. Write integration tests (`tests/web_integration/`).
10. Create `Procfile` and Heroku deployment docs.
11. Deploy to Heroku staging, run E2E tests.
12. Update documentation.
13. Deploy to Heroku production.

### Owners
- **Lead:** Primary repository maintainer (Evert).
- **Reviewers:** Architecture team, AI/ML stakeholders.

---

## 10. Definition of Done

- [ ] All acceptance criteria implemented and verified.
- [ ] Unit tests: >80% coverage for new web module; all tests pass.
- [ ] Integration tests: all API endpoints tested with success and error paths.
- [ ] E2E tests: manual testing on phone browser (iOS + Android) with real Dropbox/OpenAI.
- [ ] CLI regression: existing CLI workflows tested and unchanged.
- [ ] Documentation:
  - [ ] Feature design doc (this document) approved and stored.
  - [ ] Implementation guide created (`docs_v2/08_Epics/08_03_Implementation/005_web-interface-mvp.md`).
  - [ ] Architecture docs updated to mention web layer.
  - [ ] README updated with web deployment instructions.
- [ ] Observability:
  - [ ] Structured logs for web actions (`web_*` events) verified.
  - [ ] Health check endpoint tested.
- [ ] Security:
  - [ ] Auth enabled by default in production config.
  - [ ] Secrets verified not exposed in logs or API responses.
  - [ ] HTTPS enforced via Heroku.
- [ ] Deployment:
  - [ ] `Procfile` created and tested.
  - [ ] Heroku staging app deployed and validated.
  - [ ] Heroku production app deployed with auth.
- [ ] Rollout:
  - [ ] CLI remains default; web is opt-in (or separate dyno).
  - [ ] Rollback plan: revert to CLI-only by disabling web dyno.

---

## 11. Appendices

### Glossary

- **MVP:** Minimum Viable Product.
- **Sidecar:** `.txt` file alongside image containing sd_caption and metadata.
- **Dyno:** Heroku's container unit for running apps.
- **ASGI:** Asynchronous Server Gateway Interface (Python web server standard).
- **FastAPI:** Modern Python web framework with async support and Pydantic integration.

### References

- Feature Request: `docs_v2/08_Epics/08_01_Feature_Request/005_web-interface-mvp.md`
- Architecture: `docs_v2/03_Architecture/ARCHITECTURE.md`
- System Design: `docs_v2/03_Architecture/SYSTEM_DESIGN.md`
- Configuration: `docs_v2/05_Configuration/CONFIGURATION.md`
- FastAPI Docs: https://fastapi.tiangolo.com/
- Heroku Python Docs: https://devcenter.heroku.com/articles/getting-started-with-python

### Example API Payloads

**GET /api/images/random (success, with sidecar):**
```json
{
  "filename": "portrait_001.jpg",
  "temp_url": "https://dl.dropboxusercontent.com/apitl/1/...",
  "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
  "caption": "Contemplative moment in soft afternoon light. #FineArtPhotography #PortraitArt",
  "sd_caption": "Fine-art portrait, soft natural lighting, contemplative mood, neutral tones, shallow depth of field",
  "metadata": {
    "created": "2025-11-19T14:30:00Z",
    "sd_caption_version": "v1.0",
    "model_version": "gpt-4o-mini",
    "artist_alias": "PhotoArtist"
  },
  "has_sidecar": true
}
```

**POST /api/images/portrait_001.jpg/analyze (success):**
```json
{
  "filename": "portrait_001.jpg",
  "description": "A fine-art portrait featuring soft natural lighting and a contemplative mood",
  "mood": "contemplative",
  "tags": ["portrait", "fine_art", "natural_lighting", "neutral_tones", "shallow_dof"],
  "nsfw": false,
  "caption": "Contemplative moment in soft afternoon light. #FineArtPhotography #PortraitArt",
  "sd_caption": "Fine-art portrait, soft natural lighting, contemplative mood, neutral tones, shallow depth of field",
  "sidecar_written": true
}
```

**POST /api/images/portrait_001.jpg/publish (success):**
```json
{
  "filename": "portrait_001.jpg",
  "results": {
    "telegram": {
      "success": true,
      "post_id": "12345",
      "error": null
    },
    "email": {
      "success": true,
      "post_id": null,
      "error": null
    }
  },
  "archived": true,
  "any_success": true
}
```

**Error response (404):**
```json
{
  "error": "Image not found",
  "detail": "portrait_001.jpg does not exist in configured folder"
}
```

---

**End of Feature Design Document**

