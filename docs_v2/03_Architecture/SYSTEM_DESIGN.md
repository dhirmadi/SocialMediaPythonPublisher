# System Design — Social Media Publisher V2

Version: 2.0  
Last Updated: April 25, 2026

## 1. Goals and Scope
- Automate selection, analysis, captioning, and cross‑platform publishing of visual content.
- Support multiple storage backends via a storage protocol (Dropbox and S3-compatible managed storage).
- Upgrade AI stack to state‑of‑the‑art multimodal models (vision + text).
- Add robust prompting, safety filters, and platform‑aware formatting.
- Provide a secure web admin UI for browsing, curation, upload, and controlled publishing.
- Support orchestrator-backed multi-tenant runtime configuration and credential resolution.
- Provide a modular, testable, secure system suitable for long‑term maintenance.

Non‑Goals (V2):
- Multi-user RBAC beyond admin vs non-admin
- Persisting client-side UI queues across page reloads
- Advanced analytics dashboards (kept for future)

## 2. Users and Use Cases
- Solo creator/photographer: daily posts to Instagram/Telegram/Email with AI captions.
- Small brand: curated batch posting with approval mode before publish.
- Automation: scheduled or manual “run now” executions.
- Operator/admin: browse and manage the image library via the web UI (analyze, caption, publish, keep/remove, upload, delete).

## 3. High‑Level Capabilities
- Asset intake from storage (Dropbox folders or managed storage object prefix)
- Content analysis with multimodal AI (caption, categories, mood, safety tags)
- Caption generation with platform‑aware styles and hashtags
- Post formatting per platform (line breaks, length, media constraints)
- Parallel publishing (IG/Telegram/Email), success aggregation
- Archive on success (prevent duplicates)
- Safe retry, rate‑limit, and logging
- Web admin UI (FastAPI + static HTML/JS) for curation, upload queue, and library operations (managed storage)
- Orchestrator integration for runtime config + on-demand credential resolution (multi-tenant)

## 4. Solution Overview (Narrative)
1) V2 lists candidate images from the configured storage backend, de‑duplicates by hash/capabilities, and selects candidates.  
2) It obtains a short‑lived URL or streams bytes for analysis (no permanent external hosting).  
3) Vision LLM extracts structured analysis (description, tags, mood, safety + additional aesthetic fields).  
4) Caption generation produces platform-adaptive copy and optional sidecar content; prompts are enriched with bounded analysis context.  
5) Publishers push concurrently; any success counts; failures captured with structured error detail.  
6) On any success and not in debug/preview, the original asset is archived/moved (with sidecars).  
7) Logs are structured with correlation IDs and redaction; metering and warnings (e.g., model lifecycle) are emitted when configured.

Web UI path (admin):
1) Operator opens the web UI to browse the grid of images.  
2) Operator can upload (managed storage), search/sort/filter, select an image to view details, run analyze/caption, publish, or curate (keep/remove).  
3) While uploads are processing, the UI locks navigation-affecting controls and warns on tab close to avoid abandoning in-flight uploads.

## 5. Technology Choices (2025)
- Python 3.12, uv (primary workflow; Poetry also supported via `pyproject.toml`)
- Dropbox SDK (refresh token + app key/secret)
- S3-compatible managed storage (e.g., Cloudflare R2 / AWS S3 / MinIO) via adapter
- AI: OpenAI GPT‑4o / GPT‑4.1 family with vision (OpenAI‑only, MaaS)
- Image processing: Pillow
- Telegram: python‑telegram‑bot 20+
- Instagram: Prefer Graph API adapter; optional instagrapi adapter behind a feature flag
- Email: SMTP with app passwords
- Validation: pydantic v2
- Reliability: tenacity (retries), async rate limiter

## 6. Key Design Decisions
- Layered architecture with DI and clear interfaces for storage, AI, and publishers.
- Async orchestration with blocking adapters wrapped via to_thread where needed.
- Platform plugins allow easy addition/removal of destinations.
- Prompt templates as versioned assets; model swap without rewriting business logic.
- Strict config validation and early fail‑fast.

## 7. User Journeys
- “Post now”: Manual run with a selected profile config; preview optional.
- “Scheduled post”: Cron or external scheduler triggers CLI entrypoint.
- “Dry run”: Debug mode generates caption and previews but does not archive.
- “Review in Web UI”: Browse grid → analyze/caption → publish or curate → optional managed-storage upload/delete/move.

## 8. Success Criteria
- < 30s typical end‑to‑end latency for a single image
- 95%+ caption acceptance without manual edits
- Zero credential leaks; secrets never logged
- > 80% automated test coverage on core logic


