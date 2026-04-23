# Changelog

All notable changes to the Social Media Python Publisher project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added - PUB-037: Multi-Select & Bulk Delete
- **Multi-select mode** in the image grid — toggle via toolbar button, ctrl/cmd+click or long-press to select multiple thumbnails
- **Bulk delete** with single confirmation dialog, sequential deletion with per-file progress
- Select all on page, selection counter, Escape to exit multi-select
- Gated behind existing `delete_enabled` feature flag

### Added - PUB-036: Upload Queue with Client-Side Rate Limiting
- **Visual upload queue** showing per-file status: queued, uploading, done, failed
- **Sequential processing** with client-side pacing to stay within the server's 10/min rate limit
- **Auto-retry on 429** with backoff instead of permanent failure
- Grid refreshes on completion to show newly uploaded images

### Added - PUB-034: Usage Metering
- **`OrchestratorClient.post_usage()`** method calls `POST /v1/billing/usage` with retry, idempotency key dedup, and proper error handling (422 → `UsageMeteringError`, 403 → `CredentialResolutionError`)
- **`AIUsage` dataclass** returned from all OpenAI API calls (vision analysis + caption generation) carrying `response_id`, `total_tokens`, `prompt_tokens`, `completion_tokens`
- **`UsageMeter` fire-and-forget collaborator** — emits `ai_tokens` metric after each successful AI call; failures are logged but never block the workflow
- **403 disambiguation** on `resolve_credentials` — new `InsufficientBalanceError` subclass distinguishes "out of credits" from "bad service token"
- Standalone mode: no metering calls when no orchestrator is configured

### Added - PUB-025: Platform-Adaptive Captions
- **Per-platform caption generation** — single OpenAI call produces distinct captions tailored to each enabled platform (Telegram, Instagram, Email) instead of one caption formatted N ways
- **`CaptionSpec.for_platforms()`** factory builds platform-specific specs from `ai_prompts.yaml` style registry
- **`generate_multi()` / `generate_multi_with_sd()`** methods on `CaptionGeneratorOpenAI` for multi-platform JSON responses
- **Platform style registry** in `config/static/ai_prompts.yaml` — per-platform style directives, max lengths, and hashtag policies
- **Workflow + web service integration** — `WorkflowOrchestrator.execute()` and `WebImageService.analyze_and_caption()` use multi-caption generation; individual captions passed to each publisher
- Backwards-compatible: `for_config()` preserved, single-caption fallback for generators without multi support

### Added - PUB-033: Unified Image Browser
- **Thumbnail grid view** replaces both the old browse modal and the separate library panel — one unified experience for browsing and managing images
- **Grid ↔ detail view state machine** — click a thumbnail to enter detail view (analyze/publish/keep/remove), "Upload/Select images" button returns to the grid preserving search/sort/page state
- **Two-path data fetching** — managed storage uses `GET /api/library/objects` with full sort/filter/offset; Dropbox uses `GET /api/images/list` with client-side pagination
- **Search, sort, upload, delete** integrated into the grid toolbar (managed storage only), gated by `library_enabled` and `delete_enabled` feature flags
- **`storage_provider` field** added to `GET /api/config/features` response — frontend uses this to branch UI capabilities
- **Old code removed** — `#panel-library` HTML, `showBrowseModal()`, `apiGetRandom()`, `initReviewMode()`, review mode variables, and all library-panel-specific JS functions
- Mobile-responsive grid layout (2 columns on small screens, 3-4 on larger)

### Added - PUB-032: Admin Library — Sorting & Filtering
- **Buffered-window sort/filter** on `GET /api/library/objects` — scan up to `scan_budget` S3 keys (default 5000, configurable via `LIBRARY_SCAN_BUDGET`), filter/sort in memory, paginate with offset/limit
- Sort by `name` (default), `last_modified`, or `size` in `asc`/`desc` order
- Filename substring filter (`q` parameter, case-insensitive, path-traversal-safe)
- Response extended with `total_in_window` (count of matching objects) and `truncated` (true when scan budget reached)
- Offset-based pagination (`offset`/`limit`) for sort/filter path; legacy `cursor`-based pagination preserved for backwards compatibility
- Invalid `sort`/`order` values return 400 with clear JSON error
- **Web UI**: search input (300ms debounce), sort dropdown, order toggle, "Showing X–Y of Z" count, Previous/Next pagination
- Empty state and truncation indicator in UI
- 609 tests passing including dedicated sort/filter test suite

### Added - PUB-031: Managed Storage Migration & Admin Library
- **Migration CLI** (`publisher_v2/tools/migrate_storage.py`) — standalone async tool for copying images + sidecars from Dropbox to managed storage (Cloudflare R2)
- Supports `--dry-run`, `--limit N`, `--resume` (idempotent skip on existing keys), structured JSON progress logging
- Preserves subfolder structure (`archive/`, `keep/`, `remove/`) during migration
- Per-file error handling with summary at exit; no secrets in log output
- **Admin Library API** (`web/routers/library.py`) — 4 endpoints for managed storage file management:
  - `GET /api/library/objects` — paginated object listing with folder filter
  - `POST /api/library/upload` — multipart upload with MIME (`image/jpeg`, `image/png`) and size (20 MB) validation
  - `DELETE /api/library/objects/{filename}` — delete image + sidecar
  - `POST /api/library/objects/{filename}/move` — move between logical folders
- All library endpoints gated behind `require_auth` + `require_admin`; upload rate-limited to 10/min per session
- Returns 404 for Dropbox-only instances (library is managed-storage-only)
- **Admin Library UI** — library panel in admin section with upload, delete, move controls; paginated object list with folder filter; confirmation dialogs; mobile-responsive
- **Feature flag**: `FeaturesConfig.library_enabled` auto-enabled for managed instances, overridable via `FEATURE_LIBRARY` env var
- `/api/config/features` extended with `library_enabled`
- `python-multipart` dependency added for file upload handling
- Architecture docs updated with library endpoints and migration CLI reference
- 554 tests passing including migration, library API, feature flag, and UI test suites

### Added - PUB-024: Managed Storage Adapter
- **`ManagedStorage`** adapter (`services/managed_storage.py`) implementing `StorageProtocol` for S3-compatible backends (Cloudflare R2, AWS S3, MinIO)
- All 14 protocol methods: `list_images`, `download_image`, `get_temporary_link` (pre-signed URLs), `get_thumbnail` (Pillow + LRU cache), `archive_image`, `move_image_with_sidecars`, `delete_file_with_sidecar`, `write_sidecar_text`, `download_sidecar_if_exists`, `get_file_metadata`, `list_images_with_hashes`, `supports_content_hashing`, `ensure_folder_exists` (no-op)
- All S3 operations wrapped in `asyncio.to_thread` with exponential backoff retry on transient errors
- **`StoragePathConfig`** — provider-agnostic path model replacing all 26 `config.dropbox.*` path accesses with `config.storage_paths.*`
- **`ManagedStorageConfig`** and **`ManagedStorageCredentials`** models for R2/S3 credential handling
- **Storage factory** (`create_storage()`) dispatching `DropboxStorage` or `ManagedStorage` based on config
- `ApplicationConfig.dropbox` now optional (`DropboxConfig | None`); model validator enforces exactly one provider
- `OrchestratorConfigSource` branches on `storage.provider` — managed tenants resolve R2 credentials, Dropbox tenants work identically
- Standalone mode supports `STORAGE_PROVIDER=managed` with `R2_*` env vars
- `SanitizingFilter` updated to redact R2/S3 credential keys in logs
- `boto3` + `boto3-stubs` added as dependencies; `Pillow` already present
- 508 tests passing, including dedicated suites for managed storage, config, and storage factory

### Added - PUB-023: Storage Protocol Extraction
- **`StorageProtocol`** formal interface (`typing.Protocol`) in `services/storage_protocol.py` defining all 14 storage methods consumed by workflow, web service, and sidecar utilities
- **Protocol-level thumbnail types** (`ThumbnailSize`, `ThumbnailFormat` as `StrEnum`) replacing Dropbox SDK enums in the public interface
- **`supports_content_hashing()`** capability method replacing fragile `hasattr`/`getattr` duck-typing in workflow image selection
- All consumers (`WorkflowOrchestrator`, `WebImageService`, `generate_and_upload_sidecar`) now type-hint `StorageProtocol` instead of `DropboxStorage`
- `BaseDummyStorage` and test dummies updated to implement the protocol
- Pure refactor — zero behavior change; unblocks PUB-024 (Managed Storage Adapter)

### Added - Feature 022: Orchestrator Schema V2 Integration
- **ConfigSource abstraction** to support env-first standalone mode and orchestrator-backed multi-tenant mode
- **Host normalization/validation** and tenant extraction utilities
- **Orchestrator runtime config integration** (schema v1 + v2 parsing) with in-memory LRU+TTL caching and stale serving
- **Credential resolution** via orchestrator (`dropbox`, `openai`, `telegram`, `smtp`) with retry policy and in-memory caching + single-flight
- **POST-preferred runtime-by-host** with GET fallback on 405 (per-process cached decision)
- **Tenant-aware web middleware** and per-tenant service lifecycle (LRU+TTL tenant service cache)
- **Health endpoints**: `/health/live` and `/health/ready` (readiness checks orchestrator connectivity when configured)

## [2.6.0] - 2025-11-22

### Added - Feature 012: Centralized Configuration & i18n
- **Static configuration layer** for AI prompts, platform limits, service limits, preview text, and web UI text
- Five new YAML configuration files under `publisher_v2/config/static/`:
  - `ai_prompts.yaml` — Vision analysis and caption generation prompts
  - `platform_limits.yaml` — Caption lengths, hashtag limits, resize widths
  - `service_limits.yaml` — Rate limits, delays, timeouts, cache TTLs
  - `preview_text.yaml` — CLI preview mode headers and messages
  - `web_ui_text.en.yaml` — Web UI strings (buttons, panels, placeholders, dialogs)
- `StaticConfig` loader with graceful fallback to in-code defaults
- `PV2_STATIC_CONFIG_DIR` environment variable for custom config directory
- `AI_RATE_PER_MINUTE` environment variable override for OpenAI rate limiting
- **i18n capability** for web UI — all user-facing text externalized and ready for localization
- `/api/config/web_ui_text` endpoint for client-side i18n text access
- Jinja2 template injection of localized text with fallbacks

### Changed
- AI prompts now read from static config with fallback to existing defaults (zero behavior change)
- Platform caption limits now read from static config (Instagram 2200/30 hashtags, Telegram 4096, Email 240)
- Web UI text now sourced from YAML with English as default locale
- Service limits (AI rate, Instagram delays, web cache TTL) externalized to YAML
- Preview mode text now sourced from static config
- `WebImageService` cache TTL configurable via static config (default 30s preserved)
- Instagram publisher delay range configurable via static config (default [1,3] preserved)
- Documentation updated: `CONFIGURATION.md`, `ARCHITECTURE.md`, `README.md`, and new i18n guides

### Technical
- All changes are **backward-compatible** — static config is optional and falls back to existing defaults
- Static config loaded once at startup and cached (`@lru_cache`)
- Zero runtime performance impact (1-2ms startup overhead)
- All 210 tests passing
- No breaking changes to CLI, web API, or configuration schema

### Documentation
- Feature 012 request, design, plans, and shipped docs in `docs_v2/08_Epics/004_deployment_ops_modernization/012_central_config_i18n_text/`
- i18n activation summary with how-to guides in `docs_v2/08_Epics/004_deployment_ops_modernization/012_i18n_activation_summary.md`
- Full implementation review with verification in `docs_v2/09_Reviews/20251122_fullreview.md`
- Updated configuration reference with three-layer model

---

### Added (V1 archived)
- Comprehensive documentation in `docs/` folder
  - Complete user guide (DOCUMENTATION.md)
  - Detailed code review report (CODE_REVIEW_REPORT.md)
  - Design specifications (DESIGN_SPECIFICATIONS.md)
  - Quick reference summary (REVIEW_SUMMARY.md)
  - SMTP update documentation (SMTP_UPDATE_SUMMARY.md)
  - Setup guide moved to `docs/reports/` (SETUP_COMPLETE.md)
- GitHub integration
  - Security scan workflow (automated weekly scans)
  - Code quality workflow (automated checks)
  - Bug report template
  - Feature request template
  - Pull request template
- Development tools
  - Makefile with 15+ commands
  - Pre-commit hooks configuration
  - EditorConfig for consistent formatting
  - requirements-dev.txt for development dependencies
- Security enhancements
  - Enhanced .gitignore with 40+ security patterns
  - .cursorignore to protect sensitive data from AI indexing
  - SECURITY.md with security policy
  - Automated secret scanning
- Configurable SMTP settings in Email configuration
  - `smtp_server` option to support any SMTP provider
  - `smtp_port` option to customize port (587, 465, 25)
  - Backward compatible with default Gmail settings
- CHANGELOG.md in project root for version tracking

### Changed
- **BREAKING**: Moved all documentation to `docs/` folder
- **IMPORTANT**: Email SMTP server is now configurable via INI file
  - Previously hardcoded to `smtp.gmail.com:587`
  - Now supports Gmail, Outlook, Yahoo, and custom SMTP servers
  - Defaults to Gmail if not specified (backward compatible)
- Updated example configuration file with better comments
- Improved configuration file formatting and clarity
- Updated README with new documentation structure
- Organized reports into `docs/reports/` subdirectory
- Updated CODE_REVIEW_REPORT.md to reflect recent improvements
  - Overall rating improved from B- (6.0/10) to B+ (7.1/10)
  - Documented all resolved issues
  - Added "Recent Improvements" section

### Fixed
- Hardcoded SMTP server issue - now configurable via config file
- Configuration file example had inconsistent formatting
- Missing default values for optional Email configuration
- Documentation organization improved for better navigation

### Security
- Added 4 layers of credential protection
- Implemented automated security scanning
- Added secret detection in pre-commit hooks
- Enhanced gitignore to prevent credential leaks

## [1.0.0] - 2025-10-31

### Added
- Initial release
- Multi-platform social media posting (Instagram, Telegram, Email)
- AI-powered caption generation using OpenAI GPT
- Image analysis using Replicate BLIP-2
- Dropbox integration for image storage and archiving
- Configuration via INI files and environment variables
- Session management for Instagram authentication
- Debug mode for testing without archiving
- Async/await operations for I/O efficiency

### Features
- Random image selection from Dropbox
- Automatic AI-generated captions
- Multi-platform distribution
- Automatic image archiving
- Configurable hashtags
- Image resizing for Telegram

---

## Migration Guide

### Upgrading to Configurable SMTP

If you're upgrading from a version before the SMTP configuration change:

#### What Changed
The email SMTP server and port were previously hardcoded to Gmail (`smtp.gmail.com:587`). They are now configurable in your INI file.

#### Action Required (Optional)
Your existing configuration will continue to work with Gmail. However, to use other email providers or customize settings, add these lines to your config:

```ini
[Email]
sender = your-email@provider.com
recipient = recipient@example.com
smtp_server = smtp.gmail.com     # Add this line
smtp_port = 587                   # Add this line
```

#### For Other Providers

**Outlook/Office365:**
```ini
smtp_server = smtp.office365.com
smtp_port = 587
```

**Yahoo Mail:**
```ini
smtp_server = smtp.mail.yahoo.com
smtp_port = 587
```

**Custom SMTP:**
```ini
smtp_server = mail.yourdomain.com
smtp_port = 587  # Or 465 for SSL
```

#### Backward Compatibility
If you don't add these settings, the application will default to Gmail settings, maintaining backward compatibility with existing configurations.

---

## Notes

- Version numbers follow [Semantic Versioning](https://semver.org/)
- Keep this file updated with each release
- Document breaking changes clearly
- Include migration guides for major changes

