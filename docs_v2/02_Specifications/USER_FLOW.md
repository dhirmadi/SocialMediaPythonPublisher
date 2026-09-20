# User Flows — Social Media Publisher V2

Version: 3.0
Last Updated: September 19, 2026

## 1. CLI / Scheduled Flows

### 1.1 Post Now
1. Operator invokes CLI with a config path.
2. System loads config (orchestrator / env-first / legacy INI — see `SPECIFICATION.md` §2), validates it, initializes storage/AI/publisher adapters.
3. Selects an image from storage (Dropbox or managed storage), deduplicated via provider content-hash when available, else local SHA256.
4. Analyzes (vision) and captions (per-platform, in one AI call when multiple platforms are enabled).
5. Publishes to all enabled platforms in parallel; one platform failing/timing out never blocks the others.
6. Persists "posted" state, then archives the source image on any publish success (unless debug).
7. Saves the published captions to the caption-history store (for future anti-repetition context) and prints a summary with per-platform results.

### 1.2 Scheduled Post
1. Cron/systemd triggers the CLI entrypoint on a schedule.
2. Same as Post Now; logs written to file (rotation configured) instead of stdout.

### 1.3 Dry Run (`--dry-publish`)
1. Same as Post Now through caption generation.
2. Skips actual platform publish calls and skips archive.
3. Still writes the SD-caption sidecar and full logs; returns success if the pipeline executed without a fatal error.

### 1.4 Preview Mode (`--preview`)
1. Same as Post Now through AI vision analysis and caption generation (real AI calls — this is not a mock).
2. Skips publish and archive entirely; skips sidecar write, DB caption-history save, and posted-state update.
3. Displays human-readable output: image details, full vision analysis (all expanded fields when present), per-platform captions, email subject/placement.
4. No state changes anywhere — Dropbox/managed storage, local cache files, and the caption-history DB are all untouched. R2 storage-ops metering still flushes (preview reads incur real R2 request costs even though nothing is mutated).
5. Safe to run repeatedly against the same image to iterate on config/prompts.

### 1.5 Manual Selection (`--select filename.jpg`)
- Targets a specific file by name instead of the random pick; the rest of the pipeline (analyze → caption → publish → archive) proceeds normally for that file.
- It bypasses **random selection**, not the **already-published check** (#139). A file whose content hash is already recorded as posted exits 1 with `Already published: <filename>`, and the web UI returns 409 — this is what stops a double-click or a repeated run from posting the same image twice.
- `--preview` and `--dry-publish` are exempt and always run, since neither publishes or archives.
- **Recovery, no database:** the posted hashes live in `posted.json` under `$XDG_CACHE_HOME/publisher_v2` (default `~/.cache/publisher_v2/posted.json`); delete the image's SHA256 entry and re-run. `--preview` prints the hash without touching any state.
- **Recovery, with a database:** the per-platform publish rows hold the state; a `failed` row is re-leased by the next run automatically, and a `published` row is deliberately never re-published on its own.

## 2. Web Admin — Authentication

### 2.1 Auth0 Login (PUB-020, primary path)
1. Admin opens the web UI and clicks "Admin Login".
2. Redirected to Auth0 Universal Login (SSO honored if an Auth0 session already exists elsewhere).
3. On successful authentication, Publisher checks the verified email against the `ADMIN_LOGIN_EMAILS` allowlist (ignoring whitespace).
4. Match → redirected to `/` with the server-enforced `pv2_admin` session cookie (TTL clamped by `WEB_ADMIN_COOKIE_TTL_SECONDS`, default 3600s). No match → redirected to `/` with a "Permission Denied" message; no cookie is set.
5. Session expiry requires re-authentication through the same flow.
6. All auth events (`auth_login_start`, `auth_login_success`, `auth_login_denied`, `auth_logout`) are structured-logged for audit.

### 2.2 Legacy Bearer/Basic Auth (CLI/script automation, unaffected by Auth0)
- `WEB_AUTH_TOKEN` (Bearer) or `WEB_AUTH_USER`/`WEB_AUTH_PASS` (Basic) gate mutating API calls independent of the browser session — used by scripts/automation, not the interactive admin UI.

### 2.3 Anonymous Viewing (`FEATURE_AUTO_VIEW=true`, optional)
- When enabled, unauthenticated visitors can view a random image (`GET /api/images/random` and thumbnails) but cannot analyze, publish, curate, or manage the library — every mutating endpoint still requires an admin session or Bearer/Basic auth.

## 3. Web Admin — Browse / Review / Publish

1. Admin opens `GET /`; UI loads feature flags (`/api/config/features`), publisher enablement (`/api/config/publishers`), and i18n text.
2. UI fetches images for the grid: managed-storage library listing (`/api/library/objects`, sortable/filterable, PUB-032) or Dropbox listing (`/api/images/list`), depending on the configured storage backend.
3. Two navigation modes (PUB-019), remembered in `localStorage`:
   - **Publish Mode** (default): swipe left / "Next" loads a new random image; swipe right / "Previous" is disabled (there is no meaningful "previous" for a random stream).
   - **Review Mode**: images load in alphanumeric filename order; swipe left/right or Next/Previous step forward/back through the sorted list; an "Image X of Y" position indicator is shown.
4. Admin selects an image to view details (thumbnail loads first for speed, PUB-018; full-size on demand).
5. Admin may run analyze/caption (`POST /api/images/{filename}/analyze`), publish (`POST /.../publish`), or curate:
   - **Keep** (`POST /.../keep`) — moves the image + sidecars to the keep subfolder.
   - **Remove** (`POST /.../remove`) — moves the image + sidecars to the remove subfolder.
   - **Delete** (`POST /.../delete`, admin only, gated by `delete_enabled`, off by default) — permanently deletes the image + sidecars; irreversible.
6. If publish succeeds and archiving is enabled, the image is archived/moved together with its sidecars in the same operation.
7. Admin can view/edit their voice-profile examples (`GET`/`POST /api/config/voice-profile`) used for brand-voice-matched caption generation when `voice_matching_enabled` is on.

## 4. Web Admin (Managed Storage Only) — Library Management

1. Admin uploads one or more images via the grid toolbar; UI shows a client-side upload queue with per-file progress, client-side rate limiting to stay under the server's upload rate limit, and automatic retry on `429` (PUB-036).
2. While uploads are actively processing, the UI disables controls that would abandon uploads and warns on tab close (PUB-042).
3. Admin can delete objects: single delete via the per-thumbnail control, or multi-select + bulk delete with one confirmation (client-side loop over the single-delete endpoint, reusing the upload-queue progress pattern, PUB-037).
4. Admin can move objects between logical folders (root/keep/remove/archive) via `POST /api/library/objects/{filename}/move`.
5. Admin can filter by filename and sort by name/date/size (PUB-032), and choose the grid page size (10/25/50/100, remembered across sessions, PUB-044).

## 5. Ops — Managed Storage Migration (PUB-031, standalone, not a web/CLI publish flow)

1. Operator runs the migration CLI against an existing Dropbox-backed instance: `uv run python -m publisher_v2.tools.migrate_storage --source-folder <path> --target-prefix <prefix> [--dry-run] [--limit N] [--no-resume]`.
2. Tool copies images + sidecars from Dropbox to managed storage (R2/S3), reporting progress; supports dry-run (no writes) and is idempotent/resumable if interrupted.
3. Operator validates the managed-storage-backed instance, then cuts the instance's config over from Dropbox to managed storage (separately, via the orchestrator or env config).

## 6. Secondary Flows
- **Re-queue on partial failure**: if some platforms fail during publish, the run does not archive as a full failure — if at least one platform succeeded, the image still archives; a fully-failed run is not re-archived and may be retried on the next scheduled/manual run.
- **Model lifecycle warnings**: if a configured OpenAI model is approaching deprecation (orchestrator-delivered advisory metadata, PUB-040), a structured warning is logged at config load — this is observability only and never blocks a run.

## 7. Error Handling and Recovery
- Transient API errors (OpenAI, Dropbox, SMTP, Telegram, orchestrator): retry with exponential backoff; permanent errors (bad request, auth failure, malformed response) fail fast without burning the retry budget.
- Platform hard failures during publish: recorded as a per-platform error result; every other enabled platform still runs to completion.
- Usage-metering call failures (`POST /v1/billing/usage`): logged and swallowed; never fail the underlying workflow.
- Configuration validation failure: exits early (CLI) or fails health-check (web) with an actionable message; never partially initializes.
- Orchestrator unavailable (5xx/timeout) on runtime-config or credential-resolve calls: treated as a transient dependency failure — retried with backoff, then surfaced as a service error rather than falling back to stale/incorrect tenant config.

## 8. UX and CLI Reference
CLI flags:
- `--config path/to.ini` (accepted but ignored since #97 stage 4; configuration is env-first)
- `--env path/to/.env` (optional; defaults to `.env` in the working directory)
- `--debug` (overrides `content.debug` to `true` for this run)
- `--select filename.jpg` (manual target instead of random/dedup selection)
- `--dry-publish` (run the full pipeline but skip actual platform publish and archive)
- `--preview` (side-effect-free preview; see §1.4)
