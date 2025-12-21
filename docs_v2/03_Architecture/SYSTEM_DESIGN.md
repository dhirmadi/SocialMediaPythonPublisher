# System Design — Social Media Publisher V2

Version: 2.0  
Last Updated: November 7, 2025

## 1. Goals and Scope
- Automate selection, analysis, captioning, and cross‑platform publishing of visual content.
- Keep Dropbox as the source of truth for assets (input + archive).
- Upgrade AI stack to state‑of‑the‑art multimodal models (vision + text).
- Add robust prompting, safety filters, and platform‑aware formatting.
- Provide a modular, testable, secure system suitable for long‑term maintenance.

Non‑Goals (V2):
- Web dashboard
- Multi‑tenant teams
- Advanced analytics (kept for future)

## 2. Users and Use Cases
- Solo creator/photographer: daily posts to Instagram/Telegram/Email with AI captions.
- Small brand: curated batch posting with approval mode before publish.
- Automation: scheduled or manual “run now” executions.

## 3. High‑Level Capabilities
- Asset intake from Dropbox folder(s)
- Content analysis with multimodal AI (caption, categories, mood, safety tags)
- Caption generation with platform‑aware styles and hashtags
- Post formatting per platform (line breaks, length, media constraints)
- Parallel publishing (IG/Telegram/Email), success aggregation
- Archive on success (prevent duplicates)
- Safe retry, rate‑limit, and logging

## 4. Solution Overview (Narrative)
1) V2 scans the configured Dropbox folder, de‑duplicates by hash, and selects candidates.  
2) It obtains a short‑lived URL or streams bytes for analysis (no permanent external hosting).  
3) Vision LLM extracts: scene, entities, mood, NSFW/safety, tags.  
4) Caption LLM generates platform‑aware copy, using prompt templates + style guides + provided hashtags.  
5) Publishers push concurrently; any success counts; failures captured with structured error detail.  
6) On any success and not in debug, the original asset is moved to `/archive`.  
7) Logs include correlation IDs, sanitized for secrets/PII; metrics emitted for success/failure.

## 5. Technology Choices (2025)
- Python 3.12, uv (primary workflow; Poetry also supported via `pyproject.toml`)
- Dropbox SDK (refresh token + app key/secret)
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

## 8. Success Criteria
- < 30s typical end‑to‑end latency for a single image
- 95%+ caption acceptance without manual edits
- Zero credential leaks; secrets never logged
- > 80% automated test coverage on core logic


