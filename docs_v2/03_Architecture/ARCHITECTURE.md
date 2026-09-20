# Architecture — Social Media Publisher V2

Version: 2.6
Last Updated: December 21, 2025

## 1. Architecture Pattern

Layered architecture with service abstractions, dependency injection, and a **three-layer configuration model**.

```
CLI (uv run) / Scheduler / Web (FastAPI)
        ↓
Application Layer (Workflow Orchestrator, Use Cases)
        ↓
Domain Layer (Models: Image, Caption, Post, Results)
        ↓
Infrastructure Layer (Adapters)
  - Storage: StorageProtocol (DropboxStorage / ManagedStorage)
  - AI: VisionAnalyzerOpenAI, CaptionGeneratorOpenAI (OpenAI‑only)
  - Publishers: Instagram, Telegram, Email (pluggable)
        ↓
External Services (Dropbox, OpenAI, IG API, Telegram, SMTP)
```

## 2. Components

### Core Services
- **WorkflowOrchestrator**: Coordinates select → analyze → caption → publish → archive
- **ImageStorage (Protocol) + DropboxStorage / ManagedStorage**: List, download, temporary link, archive (S3-compatible via PUB-024)
- **AIService**: Composes VisionAnalyzer + CaptionGenerator and applies style templates
- **Publishers**: InstagramPublisher, TelegramPublisher, EmailPublisher

### Configuration (Three-Layer Model)
- **Config Loader** (Pydantic): Loads and validates all three config layers
  - **Secrets Layer**: `.env` only (never in repo)
  - **Dynamic Layer**: `.env` + INI (feature flags, deployment settings)
  - **Static Layer**: YAML files (AI prompts, platform limits, UI text, service limits)
- **FeaturesConfig**: Boolean toggles (`analyze_caption_enabled`, `publish_enabled`) applied globally
- **StaticConfig**: Versioned YAML files for prompts, limits, and internationalization

### Utilities
- Image ops, logging, rate limiting, retries, ID generation, caption formatting

### Dropbox retries and rate limits (#88, #132)

The Dropbox SDK's own retry loops are disabled (`max_retries_on_error=0`,
`max_retries_on_rate_limit=0`) so there is exactly one retry layer, in
`services/storage.py`. Before #132 a 429 retried **inside** the SDK with no
bound at all, so a throttled account could hang a request indefinitely.

Per decorated call: at most 3 attempts and 2 waits. A wait is the server's
`Retry-After` (`RateLimitError.backoff`) when present, otherwise exponential —
in practice **1s then 2s**, because at 3 attempts only two waits are ever
computed and the 8s ceiling is unreachable. **The server's value is capped at
30 seconds** (`MAX_RATE_LIMIT_BACKOFF_SECONDS`), so the worst case is 2 × 30s.

Those bounds are **per decorated call, not per request**. A single
`POST /api/images/{f}/analyze` makes several — `list_images` (30s-cached),
`get_temporary_link`, `download_sidecar_if_exists` — each with its own three
attempts, so a sustained 429 can cost a multiple of the per-call figure.
(`list_images` is cached for 30s by default, overridable via
`web_image_cache_ttl_seconds`.)

That cap is a deliberate deviation with a cost, and worth knowing when
debugging repeated 429s. Dropbox may legitimately ask for minutes; waiting
that long would tie up a dyno worker on a request nobody is still waiting for.
What the cap buys is bounded dyno-side work, **not** a response to the user:
Heroku's router already cuts the client off at 30s, so a single capped wait
spends the whole router budget and the client gets Heroku's H12 error
(**HTTP 503**, not 504) either way while the dyno keeps working.

The two retries that happen inside a window Dropbox asked us to sit out do
consume calls against an account that is already throttled. The trade favours
bounded work over minimal call volume; a batch or CLI context would reasonably
choose the opposite — `tools/migrate_storage.py` makes at least two decorated
calls per file (the image, then the sidecar), each spending three attempts and
up to 60s of waits under a sustained 429, with no global circuit breaker.

Each attempt is one or more HTTP calls, each bounded by the 30s connect/read
timeout — not a total deadline, so a slow but steady download can run longer.
Sidecar reads on the analyze path (`download_sidecar_if_exists`) are inside
this layer too, so a transient network error there now costs 3s of backoff
(1s + 2s) plus two more attempts, each bounded by the 30s HTTP timeout, rather
than failing immediately. A not-found sidecar still short-circuits before any
raise, so a missing sidecar is never retried.

## 3. Interfaces (summaries)
Storage:
- list_images(folder) -> list[str]
- list_images_with_hashes(folder) -> list[tuple[str, str]]  (filename, Dropbox content_hash)
- download_image(folder, filename) -> bytes
- get_temporary_link(folder, filename) -> str
- get_thumbnail(folder, filename, size, format) -> bytes (server-side thumbnail, Feature 018)
- archive_image(folder, filename, archive_folder) -> None

AI:
- VisionAnalyzer.analyze(url_or_bytes) -> ImageAnalysis(caption, tags, mood, nsfw_flags)
- CaptionGenerator.generate(analysis, style, hashtags, platform) -> str
- AIService.create_caption(url_or_bytes, style, hashtags, platform) -> str

Publishers (async):
- publish(image_path, caption, context: dict | None) -> PublishResult(success: bool, post_id: Optional[str], error: Optional[str])
- is_enabled() -> bool

Web API (FastAPI):
- `GET /` → HTML UI (with i18n text injection from static config)
- `GET /api/images/random` → ImageResponse (random image with metadata, includes `thumbnail_url`)
- `GET /api/images/{filename}/thumbnail` → JPEG thumbnail bytes (fast preview, Feature 018)
- `POST /api/images/{filename}/analyze` → AnalysisResponse (run AI analysis). #147: `platform_captions` carries one caption per enabled platform and is the field to read. The legacy scalar `caption` is now **the email caption when email is enabled** (it was the first platform's), so a machine client that reads `caption` for Telegram gets a text trimmed to email's 240-character limit — read `platform_captions["telegram"]` instead. After a publish, both fields serve what that run submitted (`caption_submitted` in the sidecar) in preference to the AI's `caption_generated`.
- `POST /api/images/{filename}/publish` → PublishResponse (publish to platforms); `409` when a publish for the same image is already running in this process, or (no `DATABASE_URL`) when the image is already in the posted set (#139); `400` when `captions` does not cover exactly the enabled platforms (#147 — enforced in `WebImageService.publish_image`, not only in the route, so every caller gets the same refusal)
- `POST /api/images/{filename}/keep` → CurationResponse (move to keep folder)
- `POST /api/images/{filename}/remove` → CurationResponse (move to remove folder)
- `GET /api/config/features` → dict[str, bool] (high-level feature flags from `.env`)
- `GET /api/config/publishers` → dict[str, bool] (platform enablement state)
- `GET /api/config/web_ui_text` → dict (i18n UI text from static config)
- `GET /api/admin/status` → AdminStatusResponse (admin session status)
- `POST /api/admin/login` → AdminStatusResponse (admin login)
- `POST /api/admin/logout` → AdminStatusResponse (admin logout)
- `GET /health/live` → {"status": "ok"} (liveness)
- `GET /health/ready` → {"status": "ok"} (readiness; may check orchestrator connectivity when configured)
- `GET /health` → {"status": "ok"} (legacy/compat)

Admin Library API (PUB-031, managed storage only):
- `GET /api/library/objects` → LibraryListResponse (paginated object list; query params: prefix, cursor, limit)
- `POST /api/library/upload` → LibraryUploadResponse (multipart upload; MIME allowlist, 20 MB limit, rate limited)
- `DELETE /api/library/objects/{filename}` → LibraryDeleteResponse (delete image + sidecar)
- `POST /api/library/objects/{filename}/move` → LibraryMoveResponse (move to keep/remove/archive/root)

Migration CLI (PUB-031, standalone tool):
- `uv run python -m publisher_v2.tools.migrate_storage --source-folder <path> --target-prefix <prefix>`
- Flags: `--dry-run`, `--limit N`, `--no-resume`, `--archive-folder`
- Resume is **presence-based** (#142): a target key that already exists is skipped,
  whatever its content. `--no-resume` forces a re-copy of everything. This retires
  PUB-031 AC5's "re-copy when the Dropbox `content_hash` differs from the target
  `ETag`" clause, which was never implementable: R2's ETag is an MD5 and Dropbox's
  `content_hash` is a block SHA256, so the two could never compare equal and the
  hash arm never fired. The tool reaches storage only through
  `ObjectStorageProtocol` (`exists`/`head_object`/`put_object`), so every call is
  metered. A `head_object` that fails for any reason other than absence — a 403,
  a throttle — still *reports* absent, so the object is re-copied (overwriting,
  never losing data); what changed is that the fault is no longer silent:
  `head_object_failed` is logged, and `migration_presence_unknown` when the
  presence check itself raises.

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
- Local or server with **uv** + Python 3.12 (Poetry also supported)
- Cron/systemd/CI scheduler for recurring jobs
- Optional containerization; secrets via env
- Heroku: `WEB_TRUST_FORWARDED_FOR=true` is required (CSRF and the Auth0 callback read the scheme from `X-Forwarded-Proto`); `FORWARDED_ALLOW_IPS` is not used and the `Procfile` does not trust all proxies. See [CONFIGURATION §10.2](../05_Configuration/CONFIGURATION.md) (#129)

## 7. Observability
- Structured logging with correlation IDs and redaction
- Success/failure counters per platform
- Timing for analysis, captioning, and publishing
- Static config load warnings (missing/corrupt YAML files)

## 8. Configuration Architecture

### Three-Layer Model

```
┌─────────────────────────────────────────────┐
│ SECRETS (.env only)                         │
│ - DROPBOX_APP_KEY, OPENAI_API_KEY, etc.    │
│ - Never in repo, env-only                   │
└─────────────────────────────────────────────┘
            ↓
┌─────────────────────────────────────────────┐
│ DYNAMIC (.env + INI)                        │
│ - Feature flags: FEATURE_ANALYZE_CAPTION    │
│ - Platform enablement: [Content].telegram   │
│ - Folders: [Dropbox].image_folder           │
└─────────────────────────────────────────────┘
            ↓
┌─────────────────────────────────────────────┐
│ STATIC (YAML files, versioned)              │
│ - AI prompts: ai_prompts.yaml               │
│ - Platform limits: platform_limits.yaml     │
│ - Service limits: service_limits.yaml       │
│ - Preview text: preview_text.yaml           │
│ - Web UI text: web_ui_text.en.yaml          │
└─────────────────────────────────────────────┘
            ↓
┌─────────────────────────────────────────────┐
│ ApplicationConfig (Pydantic)                │
│ - Validated, typed, immutable               │
│ - Single source of truth at runtime         │
└─────────────────────────────────────────────┘
```

### Static Config Loader

- **Location**: `publisher_v2/config/static_loader.py`
- **Load Time**: Once at process startup (cached via `@lru_cache`)
- **Fallback**: Graceful degradation to in-code defaults if files missing/corrupt
- **Override**: `PV2_STATIC_CONFIG_DIR` env var for per-environment customization
- **Performance**: ~1-2ms startup overhead, zero runtime cost

### Benefits

1. **Safety**: Secrets never accidentally committed (layer separation)
2. **Flexibility**: AI prompts tunable without code changes
3. **Internationalization**: UI text externalized for multi-language support
4. **Testability**: Static config can be mocked/overridden per test
5. **Observability**: Config load warnings logged but don't crash app

---

## See Also

- [Configuration Documentation](../05_Configuration/CONFIGURATION.md)
- [Feature 012: Central Config & i18n](../08_Epics/004_deployment_ops_modernization/012_central_config_i18n_text/012_feature.md)
- [System Design](./SYSTEM_DESIGN.md)
