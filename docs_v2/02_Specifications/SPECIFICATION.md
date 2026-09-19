# Implementation Specification — Social Media Publisher V2

Version: 3.0
Last Updated: September 19, 2026

This document is the ground truth for implementation. An AI coder can build V2 using this spec
alone. `docs_v2/05_Configuration/CONFIGURATION.md` is the operator-focused config guide
(env var tables, INI schema, migration guides) but is not yet fully in sync with every field
below — where the two disagree or one is missing a field, trust `publisher_v2/src/publisher_v2/config/schema.py`
(source of truth) and file a doc-sync fix. `docs_v2/roadmap/archive/PUB-NNN_*.md` is the
per-feature contract (Problem/User Story/Scope/Acceptance Criteria) each capability below was
built from.

## 1. Environment and Tooling
- Python 3.12
- **uv** (primary workflow; `uv run ...` for CLI/test commands)
- Dev tools: ruff (format+lint), mypy, pytest (+asyncio, +cov), bandit, detect-secrets/gitleaks (via pre-commit)

## 2. Configuration

Full field-by-field reference: `docs_v2/05_Configuration/CONFIGURATION.md`. Summary:

Publisher V2 uses a **three-layer configuration model**:
1. **Secrets** — `.env` only, never in repo, never logged.
2. **Dynamic** — `.env` + INI (or JSON env vars — see below), feature flags, deployment settings.
3. **Static** — versioned YAML files (AI prompts, platform limits, service limits, UI text).

There are three supported **operating modes**, in order of precedence at load time:

1. **Multi-tenant orchestrator mode** (`ORCHESTRATOR_BASE_URL` set) — **default production
   mode** (PUB-022). Per-tenant runtime config (non-secret) is fetched from
   `POST /v1/runtime/by-host`; per-tenant secrets are resolved on-demand from
   `POST /v1/credentials/resolve`. See §10.
2. **Single-tenant env-first mode** (PUB-021) — JSON-grouped env vars (`STORAGE_PATHS`,
   `PUBLISHERS`, `EMAIL_SERVER`, `OPENAI_SETTINGS`, `CAPTIONFILE_SETTINGS`,
   `CONFIRMATION_SETTINGS`, `CONTENT_SETTINGS`). Recommended for local/dev and standalone
   deployments; no INI file required.
3. **Legacy INI mode** (deprecated fallback) — `configfiles/*.ini` + individual env vars for
   secrets. Still supported for backward compatibility; the loader emits a `DEPRECATION`
   warning when it falls back to INI sections.

Precedence when multiple sources are present: new JSON env vars → old individual env vars →
INI file sections (first found wins per field).

Feature toggles (env vars, coarse on/off switches independent of config mode):

| Variable | Default | Behavior |
|----------|---------|----------|
| `FEATURE_ANALYZE_CAPTION` | `true` | When `false`, skips AI vision analysis, caption generation, and sidecar writes |
| `FEATURE_PUBLISH` | `true` | When `false`, skips publishing (CLI + web); web `/publish` returns 403 |
| `FEATURE_KEEP_CURATE` | `true` | When `false`, disables Keep curation; web `/keep` returns 403 |
| `FEATURE_REMOVE_CURATE` | `true` | When `false`, disables Remove curation; web `/remove` returns 403 |
| `FEATURE_AUTO_VIEW` | `false` | Allows non-admin users to view random images in the web UI |
| `FEATURE_LIBRARY` | unset (auto-resolve) | `true`/`false` force the admin library panel; when unset, `resolve_library_enabled()` auto-enables it for managed-storage instances and keeps it off for Dropbox-only instances |
| `FEATURE_ALT_TEXT` | `true` | AI-generated alt text is attached to publisher context (`alt_text_enabled`, PUB-026) |
| `FEATURE_SMART_HASHTAGS` | `true` | AI generates content-aware hashtags instead of only using the static `hashtag_string` (`smart_hashtags_enabled`, PUB-028) |
| `FEATURE_VOICE_MATCHING` | unset → `true` when a voice profile exists, else `false` | Injects `content.voice_profile` examples into caption prompts for tone matching (`voice_matching_enabled`, PUB-029, PUB-039). Explicit value wins over the profile-derived default (#131) |
| `FEATURE_STORAGE_OPS_METERING` | `false` | Emits R2 `storage_ops_requests` usage events to the orchestrator (`storage_ops_metering_enabled`, PUB-045) |

`delete_enabled` (permanent delete in the review workflow) is a `FeaturesConfig` field with
default `false`, but as of this writing has **no env-var or orchestrator wiring** — it can only
be set `True` by directly constructing `FeaturesConfig` (tests do this). Treat it as
reserved/not-yet-operator-facing rather than a working toggle until a `FEATURE_DELETE` env var
(or orchestrator `features.delete_enabled`) is wired up.

## 3. Domain Models (`publisher_v2.core.models`, dataclasses)

- **`AIUsage`**: `response_id: str`, `total_tokens: int`, `prompt_tokens: int`, `completion_tokens: int` — carries OpenAI token usage out of every AI call for billing (PUB-034).
- **`Image`**: `filename`, `dropbox_path`, `sha256: str | None`, `temp_link: str | None`, `local_path: str | None`, `size_bytes: int | None`, `format: str | None`; `.extension` property.
- **`ImageAnalysis`**: `description: str`, `mood: str`, `tags: list[str]`, `nsfw: bool`, `safety_labels: list[str]`, `sd_caption: str | None`, plus expanded optional fields (PUB-003, all backward-compatible, `null`/`[]` when unknown): `subject`, `style`, `lighting`, `camera`, `clothing_or_accessories`, `aesthetic_terms: list[str]`, `pose`, `composition`, `background`, `color_palette`, `alt_text` (PUB-026, ≤125 chars, screen-reader description), and the caption-facing `sensory_detail: list[str]` (up to 3) and `mood_note` (#138 — written for the caption writer, deliberately excluded from the sidecar metadata block).
- **`CaptionSpec`**: `platform`, `style`, `hashtags`, `max_length`, `examples: tuple[str, ...]` (voice-profile examples only since #138 — no static example captions ship with the app, and an `examples:` key left in a `PV2_STATIC_CONFIG_DIR` override is stripped with a warning), `guidance: str`, `smart_hashtags: bool`, `closing: "question" | "statement" | "any"` (#138 — a mandated closing also suppresses the "recent closing pattern to avoid" constraint, which would otherwise forbid it). `CaptionSpec.for_platforms(config)` builds one spec per enabled publisher from the `platform_captions` registry in `ai_prompts.yaml`, prepending voice-profile examples when `voice_matching_enabled` (PUB-039) and propagating `smart_hashtags_enabled` (PUB-028). `CaptionSpec.for_config(config)` is a deprecated single-spec shim kept for backward compatibility.
- **`PublishResult`**: `success: bool`, `platform: str`, `post_id: str | None`, `error: str | None`.
- **`WorkflowResult`**: `success`, `image_name`, `caption`, `publish_results: dict[str, PublishResult]`, `archived: bool`, `error: str | None`, `correlation_id: str | None`, `finished_at`, `platform_captions: dict[str, str]`, plus preview-only fields: `image_analysis`, `caption_spec`, `dropbox_url`, `sha256`, `image_folder` (populated only when `preview_mode=True`, otherwise `None` — preview never mutates state but does surface everything the run would have used).

## 4. Caption Files and Sidecars (PUB-001, PUB-004)

Every processed image gets a companion `<image>.txt` sidecar (same basename, same folder,
moves with the image on archive/curation). **Line 1 is the pure `sd_caption`** — training
pipelines that read only line 1 must never see anything else there. When
`captionfile.extended_metadata_enabled` is on, a `# ---` separator followed by `#`-prefixed
metadata lines is appended below it (phase-1 identity fields always on when `sd_caption`
exists; phase-2 contextual fields — `lighting`, `pose`, `materials`, `art_style`, `tags`,
`moderation`, plus any of the PUB-003 expanded fields — gated by the flag). A field with no
value is omitted entirely, never written as `# field: null`. See
`.cursor/skills/caption-sidecar-schema/SKILL.md` for the exact worked format and the
enforcement rule (never rename/repurpose an existing field). In preview/dry/debug modes the
sidecar is never written to disk; the full content is printed instead.

## 5. Interfaces

### Storage (`publisher_v2.services.storage_protocol.StorageProtocol`)
Runtime-checkable `Protocol`; `DropboxStorage` and `ManagedStorage` both satisfy it structurally (no explicit inheritance required):
- `list_images(folder) -> list[str]`
- `list_images_with_hashes(folder) -> list[tuple[str, str]]` (filename, provider content-hash — dedup fast path)
- `download_image(folder, filename) -> bytes`
- `get_temporary_link(folder, filename) -> str`
- `get_file_metadata(folder, filename) -> dict[str, str]`
- `write_sidecar_text(folder, filename, text) -> None`
- `download_sidecar_if_exists(folder, filename) -> bytes | None`
- `archive_image(folder, filename, archive_folder) -> None`
- `move_image_with_sidecars(folder, filename, target_subfolder) -> None` (keep/remove curation)
- `delete_file_with_sidecar(folder, filename) -> None` (permanent delete, gated by `delete_enabled`)
- `ensure_folder_exists(folder_path) -> None`
- `get_thumbnail(folder, filename, size: ThumbnailSize, format: ThumbnailFormat) -> bytes` (PUB-018; sizes `w256h256`…`w1024h768`, formats `jpeg`/`png`)
- `supports_content_hashing() -> bool` (selects the metadata-based dedup path in `WorkflowOrchestrator._select_image`)

### AI (`publisher_v2.services.ai`, OpenAI only)
- **`VisionAnalyzerOpenAI.analyze(url) -> tuple[ImageAnalysis, AIUsage | None]`** — cost-optimized (PUB-041): downloads+resizes to `vision_max_dimension` px and sends with `vision_detail` (default 1024px/`low`); on failure, when `vision_fallback_enabled`, retries once at `vision_fallback_max_dimension`/`vision_fallback_detail` (default 2048px/`high`) and returns combined usage. Uses `response_format={"type": "json_object"}`; a non-JSON response raises rather than fabricating a description from raw text (prevents attacker-controlled image-overlay text from reaching captions).
- **`CaptionGeneratorOpenAI`** — single caption (`generate`), single caption+SD pair in one call (`generate_with_sd`), **multi-platform caption generation in one call** (`generate_multi`, `generate_multi_with_sd` — PUB-025), each returning `tuple[..., AIUsage | None]`. Builds prompts from `build_analysis_context` (PUB-041, sanitizes vision-extracted free text against prompt-injection markers before re-interpolating it), optional `build_voice_examples_block` (PUB-029, hardened BEGIN/END-delimited, budget-truncated via `truncate_voice_profile_to_budget`), and optional per-platform caption-history block (PUB-035; the production path fetches history from `CaptionStore.fetch_recent_by_platform` (DB) and renders it via `build_platform_block`'s per-platform `platform_history` — `services/ai.py`'s sidecar-scanning `fetch_caption_history()`/`build_history_block()` are a legacy fallback retained for callers without a `CaptionStore`, e.g. tests, and are not on the live `WorkflowOrchestrator` path). Anti-repetition instructions are appended either way. Hashtags are AI-generated from the analysis when `spec.smart_hashtags` is set (PUB-028), otherwise the static `hashtags` string is appended verbatim. Short-limit platforms (`max_length <= 300`, e.g. FetLife email) get word-count instructions, lowered temperature, a `max_tokens` ceiling, and — on overshoot — an AI condense pass (`_handle_overshoot`/`_condense_caption`, hardened with a fixed non-tenant system prompt and BEGIN/END text fencing) before falling back to `smart_truncate` (PUB-046).
- **`AIService`** — composes analyzer + generator behind a shared `AsyncRateLimiter`; `create_caption`, `create_caption_pair_from_analysis` (single-platform, falls back from SD-pair to caption-only on any generator failure), `create_multi_caption_pair_from_analysis` (multi-platform, falls back to single-platform if the generator lacks `generate_multi`). All public methods return/aggregate `list[AIUsage]` for metering.
- **`NullAIService`** — safe stub (`analyzer = generator = None`) used when `analyze_caption_enabled=False`; `WorkflowOrchestrator` guards all AI calls behind that flag so this is never invoked.
- **Model lifecycle warnings** (PUB-040): `OpenAIConfig.vision_model_lifecycle` / `caption_model_lifecycle` carry advisory `ModelLifecycle(warning, shutdown_date, recommended_replacement, severity)` metadata (orchestrator-delivered); Publisher logs a structured warning at startup/config-load when a configured model is approaching deprecation. Observability only — does not block operation.
- Non-OpenAI providers (Replicate, etc.) are out of scope for V2; all AI tasks are fulfilled by OpenAI as MaaS.

### Publishers (`publisher_v2.services.publishers.base.Publisher`, ABC)
- `platform_name -> str` (property)
- `is_enabled() -> bool`
- `async publish(image_path: str, caption: str, context: dict | None = None) -> PublishResult`

Implemented: `TelegramPublisher`, `InstagramPublisher`, `EmailPublisher`. **Planned, not yet
implemented**: Bluesky (`PUB-027`, AT Protocol, NSFW self-labeling) and Mastodon/Fediverse
(`PUB-030`, sensitive-media flag + content warnings) — both `Status: Not Started` in the
roadmap; adding either is expected to be a single new class in
`publisher_v2/services/publishers/`, no orchestrator changes.

## 6. Adapters

**DropboxStorage** — refresh-token OAuth; ensures archive/keep/remove folders exist
(`files_create_folder_v2`, ignores "already exists"); prefers Dropbox `content_hash` metadata
for de-duplication, falls back to local SHA256 when hashes are unavailable.

**ManagedStorage** — S3-compatible adapter (Cloudflare R2 / AWS S3 / MinIO), implements the
same `StorageProtocol` including thumbnails and sidecar ops (PUB-023, PUB-024). Counts R2
requests for metering (`drain_ops_count()`, consumed by `StorageOpsMeter`, PUB-045). Comes
with a standalone migration CLI (PUB-031):
```
uv run python -m publisher_v2.tools.migrate_storage --source-folder <path> --target-prefix <prefix> [--dry-run] [--limit N] [--no-resume] [--archive-folder <name>]
```
Copies images + sidecars from Dropbox to managed storage; dry-run and idempotent/resumable by
design; not part of the normal publish workflow.

**OpenAI Vision Analyzer / Caption Generator** — see §5 AI interfaces above for the full
behavior (cost optimization, platform-adaptive multi-caption, brand voice, context
intelligence, smart hashtags, alt text, email length control).

**InstagramPublisher** — `instagrapi` (unofficial private-API client) only; there is no Graph
API path in V2. Resizes the image's width down to Instagram's max via
`utils.images.ensure_max_width_async` before upload (no cropping).

**TelegramPublisher** — `python-telegram-bot` 20+, async `send_photo`.

**EmailPublisher** — SMTP with STARTTLS, attaches image. FetLife-specific behavior:
- Caption placement via `caption_target` (`subject`|`body`|`both`)
- Subject prefix via `subject_mode` (`private`|`avatar`|`normal`)
- Hashtags stripped; punctuation normalized; length capped ≤240 chars (short-limit path, see §5)
- Optional confirmation email to sender with N AI-derived descriptive tags (`confirmation_tags_count`, default 5)

## 7. Feature Toggle System (PUB-009)

`FeaturesConfig` (Pydantic) is the single source of truth for all feature gating, read once at
config load and exposed via `ApplicationConfig.features` to CLI, `WorkflowOrchestrator`, and
the web layer alike: `analyze_caption_enabled`, `publish_enabled`, `keep_enabled`,
`remove_enabled`, `delete_enabled`, `auto_view_enabled`, `library_enabled`,
`alt_text_enabled`, `smart_hashtags_enabled`, `voice_matching_enabled`,
`storage_ops_metering_enabled`. Storage/Dropbox access itself is always on and cannot be
disabled. Invalid boolean values raise `ConfigurationError` at startup (accepted:
`true/false`, `1/0`, `yes/no`, `on/off`, case-insensitive).

## 8. Orchestrator (`publisher_v2.core.workflow.WorkflowOrchestrator`)

`execute(select_filename=None, dry_publish=False, preview_mode=False, caption_override=None, caption_overrides=None) -> WorkflowResult`:

1. **Select image**: dedup via provider content-hash (fast path, skips downloads for
   already-posted candidates) when `storage.supports_content_hashing()`, else legacy
   SHA256-only dedup after downloading each candidate. Honors `select_filename` for manual
   targeting.
2. **Acquire**: write to a `0600` temp file; fetch a temporary link; temp file is deleted in a
   `finally` block regardless of outcome.
3. **Analyze** (skipped, logging `feature_analyze_caption_skipped`, when
   `features.analyze_caption_enabled=False`): `VisionAnalyzerOpenAI.analyze(temp_link)`; usage
   emitted to `UsageMeter` when present.
4. **Caption**: builds one `CaptionSpec` per enabled platform via `CaptionSpec.for_platforms`;
   fetches per-platform caption history from `CaptionStore` (DB-only, PUB-035) when
   configured; builds voice-profile examples when `voice_matching_enabled`; generates
   multi-platform captions in one call via `AIService.create_multi_caption_pair_from_analysis`
   (falls back to single-platform); an explicit `caption_override` short-circuits AI entirely
   and is marked `ai_skipped=True` in telemetry. `caption_overrides` (#147, platform → text) does
   the same per platform: each publisher receives its own text, and it wins over `caption_override`. SD-caption sidecar is generated and uploaded
   when `sd_caption_enabled` (skipped in preview/dry/debug). All caption-generation usage is
   emitted to `UsageMeter`.
5. **Publish** (skipped, logging `feature_publish_skipped`, when `features.publish_enabled=False`):
   enabled publishers run concurrently via `asyncio.gather(return_exceptions=True)`, each
   wrapped in a per-publisher `asyncio.wait_for` timeout (`PUBLISH_TIMEOUT_SECONDS`, default
   120s; per-platform override `PUBLISH_TIMEOUT_<PLATFORM>_SECONDS`). A timeout or exception
   in one publisher becomes a failed `PublishResult` for that platform only — it never blocks
   or fails the others. Publisher context includes `alt_text` (PUB-026, when
   `alt_text_enabled`) and analysis tags.
6. **Persist "posted" state** before archiving (crash-safe: a mid-run crash between publish and
   archive won't cause a re-publish on the next run).
7. **Save published captions to `CaptionStore`** (DB) for future caption-history context,
   tracking per-platform truncation for monitoring — skipped in debug/dry/preview.
8. **Archive**: only if any publisher succeeded, `content.archive=true`, and not
   debug/dry/preview. Archive failure is logged and treated as idempotent (a prior crashed run
   may have already moved the file); the run is not retried automatically.
9. Always flushes the `StorageOpsMeter` (R2 request counter) in a `finally` block, even in
   preview mode, since preview still incurs real R2 read costs (PUB-045).

**Preview mode** (`preview_mode=True`) runs steps 1–4 for real (so the operator sees genuine
AI output) but **never** publishes, archives, updates posted-state, or writes sidecars/DB rows
— steps 5–7 are structurally skipped by the same guards used for dry-publish/debug. The
returned `WorkflowResult` carries the preview-only fields (`image_analysis`, `caption_spec`,
`dropbox_url`, `sha256`, `image_folder`) for a human-readable preview render.

**Curation** (`keep_image`, `remove_image`, `delete_image`) are separate orchestrator methods
gated by `features.keep_enabled`/`remove_enabled`/`delete_enabled` respectively; each moves
(or, for delete, permanently removes) the image and its sidecars via
`move_image_with_sidecars`/`delete_file_with_sidecar`. In preview/dry-run they print the
intended action and touch no storage.

## 9. Web Admin UI (FastAPI, `publisher_v2.web.app` + `web.routers.*`)

Single-page admin UI (`GET /`, vanilla JS). i18n text (`web_ui_text` static config) is
injected server-side into the Jinja2 template context and embedded as a JS global at render
time — it is **not** a separate JSON API. Endpoints below (mutating ones require web auth —
see §12):

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | HTML admin UI |
| GET | `/health`, `/health/live`, `/health/ready` | Liveness/readiness (readiness may check orchestrator connectivity) |
| GET | `/api/admin/status` | Admin session status |
| POST | `/api/admin/logout` | Clear the admin session cookie (deprecated alias of `/api/auth/logout`) |
| GET | `/auth/login`, `/auth/callback`, `/auth/logout` | Auth0 OIDC login flow (PUB-020) |
| GET | `/api/images/list` | Paginated/sortable/filterable image list (PUB-032, PUB-033) |
| GET | `/api/images/random` | Random image + metadata (`thumbnail_url` included) |
| GET | `/api/images/{filename}` | Image details |
| GET | `/api/images/{filename}/thumbnail` | Fast JPEG/PNG thumbnail (PUB-018) |
| POST | `/api/images/{filename}/analyze` | Run AI analysis + caption generation |
| POST | `/api/images/{filename}/publish` | Publish to enabled platforms. Body: `{"captions": {platform: text}}` (#147; must cover every enabled platform, else 400 — enforced in `WebImageService.publish_image`, so every caller gets it, not only this route) or legacy `{"caption": text}` for all platforms. `analyze` returns `platform_captions` + `platform_limits`; image details return `caption_generated` + `platform_limits`. After a publish, both serve the sidecar's `caption_submitted` (what the operator actually sent) in preference to the AI's `caption_generated` |
| POST | `/api/images/{filename}/keep` | Curation: move to keep folder |
| POST | `/api/images/{filename}/remove` | Curation: move to remove folder |
| POST | `/api/images/{filename}/delete` | Permanent delete (admin only, gated by `delete_enabled`) |
| GET | `/api/config/features` | High-level feature flags |
| GET | `/api/config/publishers` | Platform enablement state |
| GET / POST | `/api/config/voice-profile` | Read/write operator voice-profile examples (PUB-029, PUB-039) |
| GET | `/api/library/objects` | Managed-storage-only: paginated object list (prefix/cursor/limit) |
| POST | `/api/library/upload` | Managed-storage-only: multipart upload (MIME allowlist, 20 MB limit, rate limited) |
| DELETE | `/api/library/objects/{filename}` | Managed-storage-only: delete image + sidecar |
| POST | `/api/library/objects/{filename}/move` | Managed-storage-only: move between root/keep/remove/archive |

Web-UI features layered on top of this API (frontend-only unless noted): thumbnail-first
grid with lazy full-size loading (PUB-018), swipe gestures with distinct Publish/Review modes
and a position indicator (PUB-019), unified thumbnail grid with search/sort/filter/upload/
delete (PUB-033, PUB-032, PUB-044 configurable page size), client-side upload queue with rate
limiting, auto-retry on 429, and UI lock during active uploads (PUB-036, PUB-042), multi-select
+ bulk delete (client-side loop over the single-delete endpoint, PUB-037), and a reorganized
toolbar (PUB-038). See `docs_v2/03_Architecture/ARCHITECTURE.md` for full request/response
schemas.

## 10. Multi-Tenant Orchestrator Integration (PUB-022, PUB-034, PUB-045)

Full protocol: `docs_v2/02_Specifications/ORCHESTRATOR_SERVICE_API_INTEGRATION_GUIDE.md` and
`ORCHESTRATOR_RUNTIME_CONFIG_SCHEMA_REFERENCE.md`. Publisher calls three orchestrator service
endpoints under `/v1` (never `/api/v1`), all requiring `Authorization: Bearer
<ORCHESTRATOR_SERVICE_TOKEN>`:

1. **`POST /v1/runtime/by-host`** (GET fallback on 405) — non-secret per-tenant runtime config
   (features, storage, publishers, email_server, ai, captionfile, confirmation, content —
   schema v2). Cached by `ttl_seconds`; `config_version` is an opaque cache-invalidation hash.
2. **`POST /v1/credentials/resolve`** — resolves an opaque `credentials_ref` to actual secret
   material (Dropbox refresh token, OpenAI API key, publisher secrets). Never persisted to
   disk; `no-store` semantics honored.
3. **`POST /v1/billing/usage`** (PUB-034, PUB-045) — push-based usage metering. Publisher calls
   this after every billable OpenAI call (`metric="ai_tokens"`, `quantity=total_tokens`) via
   `UsageMeter.emit`/`emit_all`, and periodically (every 5 minutes, plus a final flush at the
   end of every `WorkflowOrchestrator.execute()` call including preview runs) for R2 storage
   operations (`metric="storage_ops_requests"`) via `StorageOpsMeter.flush`, when
   `storage_ops_metering_enabled`. Idempotency keys prevent double-billing on retry. Usage
   emission failures are logged and swallowed — they never fail the underlying workflow. A
   403 response with body `{"error": "insufficient_balance"}` raises
   `InsufficientBalanceError` (subclass of `CredentialResolutionError`) so callers can
   distinguish "workspace out of credits" from "bad service token".

Standalone (non-orchestrator) mode: `usage_meter` and `storage_ops_meter` are `None`; no
metering calls are made.

## 11. Reliability
- Retries with `tenacity` on transient network/API errors (OpenAI, Dropbox, SMTP, Telegram,
  orchestrator calls); permanent errors (bad request, auth, JSON-decode failure) short-circuit
  immediately rather than burning the retry budget.
- Async rate limiter per external service (OpenAI default 20 rpm, overridable via
  `AI_RATE_PER_MINUTE`); the AI condense pass (PUB-046) shares the same limiter rather than
  bypassing it.
- Bounded timeout per external call; per-publisher `asyncio.wait_for` isolates one platform's
  timeout from the others.
- All blocking SDK calls (`instagrapi`, `smtplib`) wrapped in `asyncio.to_thread`.

## 12. Security
- Secrets only in `.env` / orchestrator-resolved credentials; never logged (regex-pattern
  redaction for `sk-`, `r8_`, tokens, bearer headers).
- **Web auth**: mutating endpoints require either HTTP auth (`WEB_AUTH_TOKEN` Bearer, or
  `WEB_AUTH_USER`/`WEB_AUTH_PASS` Basic) or the signed, tenant/host-bound admin session cookie —
  a valid cookie alone is sufficient by default (#91 SEC-3 decision b), and
  `WEB_REQUIRE_HEADER_AUTH_WITH_COOKIE=1` additionally requires header auth for cookie sessions.
  Admin-gated actions require that cookie — the image routes call `require_admin` only when admin
  mode is configured (`is_admin_configured()`), so an instance with no admin login set up does not
  gate them — which a browser obtains through Auth0 OIDC login
  (PUB-020) gated by an email allowlist (`ADMIN_LOGIN_EMAILS`); its TTL is clamped
  (`WEB_ADMIN_COOKIE_TTL_SECONDS`, 60–3600s, default 3600). `FEATURE_AUTO_VIEW=true` permits anonymous
  viewing of random images only — never mutation.
- **Prompt-injection hardening**: vision-extracted free text is sanitized
  (`_sanitize_analysis_field`) before being re-interpolated into caption prompts; the SD
  condense pass (PUB-046) uses a fixed, non-tenant-controllable system prompt with explicit
  BEGIN/END text fencing so a malicious tenant prompt cannot steer caption rewriting; voice
  profile examples are similarly delimited and marked "style references only" (PUB-029).
- Temp files created `0600`, deleted in `finally` blocks.
- **Preview mode is side-effect free**: no publish, no archive, no state/cache mutation, no
  sidecar writes — safe to run repeatedly on the same image.
- No long-term public hosting of user images for analysis; temporary links only.

## 13. CLI

Entrypoint:
```
uv run python publisher_v2/src/publisher_v2/app.py [--env path/to/.env] [--debug] [--select filename] [--dry-publish] [--preview]
```
- `--config`: accepted for compatibility and ignored — INI support was removed in #97 stage 4. Configuration comes from the environment.
- `--env`: optional path to `.env` file (defaults to `.env` in cwd).
- `--debug`: overrides `content.debug` to `True` for this run.
- `--select filename`: target a specific file instead of random selection.
- `--dry-publish`: run the full pipeline but skip actual platform publish and archive.
- `--preview`: side-effect-free preview (see §8).

## 14. Testing
- Unit: config loader/validator, prompt builders, caption post-processor, smart_truncate, sidecar builders.
- Integration: adapters with HTTP mocked (Dropbox, OpenAI, orchestrator via `httpx.MockTransport`).
- E2E: orchestrator with staged mocks; assert archive decision, result aggregation, and metering calls.
- Coverage target: ≥80% affected modules, ≥85% overall.

## 15. Acceptance Tests (must pass)
- Generates a non-empty caption for a valid image with debug on.
- Respects per-platform length constraints (AI condense pass for short-limit platforms; smart-truncate with ellipsis otherwise).
- Archives only when at least one platform succeeded and not in debug/dry/preview.
- Redacts secrets in all log output.
- Preview mode never mutates Dropbox/managed storage state, posted-hash cache, or sidecar files.
- A failing publisher never blocks or fails sibling publishers in the same run.
- Usage-metering failures never fail the underlying workflow.

### Sidecar caption keys (#147)

| Key | Written by | Meaning |
|---|---|---|
| `caption` | publish | The single published/edited caption. One text, so it cannot represent per-platform edits. |
| `caption_generated` | analyze | The AI's own per-platform output. Never overwritten by a publish. |
| `caption_submitted` | publish | The per-platform text the last run submitted to the publishers, **including platforms whose publish failed** — a retry must show the operator their own text, not the AI's. Additive; absent on sidecars written before #147, where an operator edit lives in `caption` with `caption_edited: True` and is shown for every platform. |
