# Architecture — Social Media Publisher V2

Version: 2.0  
Last Updated: November 7, 2025

## 1. Architecture Pattern
Layered architecture with service abstractions and dependency injection.

```
CLI (poetry run) / Scheduler / Web (FastAPI)
        ↓
Application Layer (Workflow Orchestrator, Use Cases)
        ↓
Domain Layer (Models: Image, Caption, Post, Results)
        ↓
Infrastructure Layer (Adapters)
  - Storage: DropboxStorage
  - AI: VisionAnalyzerOpenAI, CaptionGeneratorOpenAI (OpenAI‑only)
  - Publishers: Instagram, Telegram, Email (pluggable)
        ↓
External Services (Dropbox, OpenAI, IG API, Telegram, SMTP)
```

## 2. Components
- WorkflowOrchestrator: coordinates select → analyze → caption → publish → archive
- ImageStorage (Protocol) + DropboxStorage: list, download, temporary link, archive
- AIService: composes VisionAnalyzer + CaptionGenerator and applies style templates
- Publishers: InstagramPublisher, TelegramPublisher, EmailPublisher
- Config Manager (pydantic): loads `.env` + INI, validates, exposes typed config
- FeaturesConfig: boolean toggles (`analyze_caption_enabled`, `publish_enabled`) applied globally across CLI + web
- Utilities: image ops, logging, rate limiting, retries, ID generation

## 3. Interfaces (summaries)
Storage:
- list_images(folder) -> list[str]
- list_images_with_hashes(folder) -> list[tuple[str, str]]  (filename, Dropbox content_hash)
- download_image(folder, filename) -> bytes
- get_temporary_link(folder, filename) -> str
- archive_image(folder, filename, archive_folder) -> None

AI:
- VisionAnalyzer.analyze(url_or_bytes) -> ImageAnalysis(caption, tags, mood, nsfw_flags)
- CaptionGenerator.generate(analysis, style, hashtags, platform) -> str
- AIService.create_caption(url_or_bytes, style, hashtags, platform) -> str

Publishers (async):
- publish(image_path, caption, context: dict | None) -> PublishResult(success: bool, post_id: Optional[str], error: Optional[str])
- is_enabled() -> bool

Web API (FastAPI):
- GET / -> HTML UI
- GET /api/images/random -> ImageResponse (random image with metadata)
- POST /api/images/{filename}/analyze -> AnalysisResponse (run AI analysis)
- POST /api/images/{filename}/publish -> PublishResponse (publish to platforms)
- GET /api/config/features -> dict[str, bool] (high-level feature flags from .env)
- GET /api/admin/status -> AdminStatusResponse (admin session status)
- POST /api/admin/login -> AdminStatusResponse (admin login)
- POST /api/admin/logout -> AdminStatusResponse (admin logout)
- GET /health -> {"status": "ok"}

## 4. Execution Model
- Async entrypoint; wrap blocking SDK methods with `asyncio.to_thread`.
- Parallel publishing with `asyncio.gather(return_exceptions=True)`.
- Retries (tenacity) for transient failures; per‑service backoff.
- Rate limiting per external API.

## 5. Data Flow (Sequence)
1) Orchestrator selects candidate image (no duplicate hash, meets filters), preferring Dropbox `content_hash` metadata for de‑duplication and falling back to local SHA256 when needed.  
2) Storage returns tmp link or bytes.  
3) Vision analysis extracts description, tags, mood, safety.  
4) Caption generator produces platform‑aware copy from templates.  
5) Publishers run in parallel; collect results.  
6) If any success and not debug → archive; cleanup temp; update posted state with SHA256 and, when available, Dropbox `content_hash`; log metrics.

### Feature Toggle Integration (v2.5+)
- `FEATURE_ANALYZE_CAPTION=false` → orchestrator skips steps 3–4; preview + web return cached sidecar data when available and log `feature_analyze_caption_skipped`.
- `FEATURE_PUBLISH=false` → orchestrator skips step 5 entirely (no publisher invocations, no archive). Web `/publish` returns 403 when toggle is off.
- Toggles are read once during config load and are exposed via `ApplicationConfig.features` for all layers (CLI, workflow, web). Storage remains always-on.

## 6. Deployment
- Local or server with Poetry + Python 3.12
- Cron/systemd/CI scheduler for recurring jobs
- Optional containerization; secrets via env

## 7. Observability
- Structured logging with correlation IDs and redaction
- Success/failure counters per platform
- Timing for analysis, captioning, and publishing


