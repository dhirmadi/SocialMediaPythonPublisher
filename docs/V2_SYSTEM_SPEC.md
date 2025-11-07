# Social Media Python Publisher V2 — System Specification

Version: 2.0  
Last Updated: November 7, 2025  
Status: Approved for implementation

---

## 1. Scope and Goals

- Rebuild the existing automation into a modular, testable, secure, and maintainable solution.
- Preserve core capabilities: select image from Dropbox; analyze with AI; generate caption; publish to Instagram, Telegram, and Email; archive on success.
- Non-breaking: deliver V2 in a separate directory so V1 can continue to run unchanged.

Out-of-scope for V2:
- Web UI/dashboard
- Multi-tenant user management
- Video processing (documented as future work)

---

## 2. Target Runtime and Tooling

- Python: 3.12 (3.11+ acceptable)  
- Package/Env: Poetry (package-mode=false)  
- Lint/Format/Types: black, isort, flake8, mypy, pylint  
- Testing: pytest (+ pytest-asyncio, pytest-cov)  
- Security: safety, bandit, pre-commit hooks  

---

## 3. High-Level Architecture

Pattern: Layered architecture with dependency injection

Layers:
- Presentation: CLI (make, poetry run)
- Application: Workflow Orchestrator (use cases)
- Domain: Domain models (Image, Caption, Post)
- Infrastructure: Adapters for Dropbox, OpenAI, Replicate, Telegram, Instagram, SMTP

Key principles:
- Interfaces (Protocols/ABCs) for storage, AI, publishers
- Concrete adapters implement interfaces and are injected
- Pure domain logic isolated from vendors

---

## 4. V2 Directory Layout (separate from V1)

```
publisher_v2/
  pyproject.toml        # poetry metadata for v2 module (optional if monorepo)
  src/
    publisher_v2/
      __init__.py
      core/
        models.py              # Image, Caption, Post, enums
        exceptions.py
        workflow.py            # WorkflowOrchestrator
      config/
        schema.py              # pydantic models
        loader.py              # .env + INI → schema
      services/
        storage.py             # ImageStorage Protocol + DropboxStorage
        ai.py                  # ImageAnalyzer, CaptionGenerator, AIService
        publishers/
          base.py              # Publisher ABC + PublishResult
          telegram.py
          instagram.py         # Adapter; Graph API preferred; instagrapi optional
          email.py
      utils/
        images.py              # resize/crop
        logging.py             # structured logging + rotation
        rate_limit.py
        retry.py
      app.py                   # CLI entrypoint
  tests/
    unit/                      # unit tests
    integration/               # adapters mocked HTTP
    e2e/                       # orchestrator smoke tests (mocks)
  README.md
```

---

## 5. Configuration Model (pydantic)

Environment via `.env`; feature flags via INI. Naming normalized:
- DROPBOX_APP_KEY
- DROPBOX_APP_SECRET (rename from DROPBOX_APP_PASSWORD)
- DROPBOX_REFRESH_TOKEN

Pydantic schema (summary):
- DropboxConfig: app_key, app_secret, refresh_token, image_folder, archive_folder="archive"
- OpenAIConfig: api_key, model, system_prompt, role_prompt
- ReplicateConfig: api_token, model
- Platforms: telegram_enabled, instagram_enabled, email_enabled
- TelegramConfig: bot_token, channel_id
- InstagramConfig: username, password | or Graph API creds
- EmailConfig: sender, recipient, password (app password), smtp_server=smtp.gmail.com, smtp_port=587
- ContentConfig: hashtag_string, archive, debug

Validation:
- Required env present; formats checked (e.g., OPENAI_API_KEY starts with sk-)
- Paths start with "/" for Dropbox

---

## 6. External Integrations

Dropbox:
- Official SDK with refresh token; pass app_key + app_secret for refresh.
- Ensure archive folder exists before move.

OpenAI:
- openai>=2.x client; async usage preferred.
- Chat Completions; consistent string returns; raise on fatal errors.

Replicate:
- Use replicate>=1.x; BLIP-2 (or configurable).  
- Prefer single pass if model supports combined caption+mood; else run in parallel.

Telegram:
- python-telegram-bot 20+; async APIs.

Instagram:
- Default: Adapter for official Graph API (safer).  
- Optional: instagrapi adapter behind feature flag with prominent disclaimer.

SMTP:
- Configurable server/port; STARTTLS or SSL; app-passwords only.

---

## 7. Core Interfaces (summaries)

Storage:
- list_images(folder) -> list[str]
- download_image(folder, filename) -> bytes
- get_temporary_link(folder, filename) -> str
- archive_image(folder, filename, archive_folder) -> None

AI:
- ImageAnalyzer.analyze(url) -> ImageAnalysis(caption, mood, description)
- CaptionGenerator.generate(description) -> str
- AIService.create_caption(url) -> str  (adds hashtags)

Publishers:
- Publisher.publish(image_path, caption) -> PublishResult
- Implementations: Telegram, Instagram, Email

Orchestrator:
- execute() -> WorkflowResult (success, image_name, caption, per-platform results, archived)
- Behavior: select → download temp → analyze → caption → publish (parallel) → archive if any success and not debug → cleanup temp

---

## 8. Error Handling, Retries, and Rate Limiting

- Custom exceptions: ConfigurationError, StorageError, AIServiceError, PublishingError
- tenacity-based retries for transient failures (OpenAI, Replicate, Dropbox, SMTP, Telegram)
- Async rate limiter per service (OpenAI, Replicate, Telegram)
- Consistent error surfaces; no sensitive data in logs

---

## 9. Security

- Secrets only in environment; `.env` local only; `.ini` for non-secrets
- Optional system keyring support for high-risk secrets (Instagram/email)
- Session data (e.g., Instagram) encrypted at rest (Fernet) when feasible
- Log sanitization for tokens and passwords
- Temporary files created with 0600 and securely deleted after use

---

## 10. Observability

- Structured logging (JSON-capable formatter) with rotation
- Log categories: storage, ai, publish, workflow
- Correlation id per run (uuid4)

---

## 11. Testing Strategy

- Unit tests for config validation, utils, pure domain functions
- Integration tests for adapters (HTTP mocked)
- E2E: orchestrator with all adapters mocked
- Coverage goal: 80%+

---

## 12. Performance

- Parallel platform publishes (async gather)
- Replicate dual calls executed concurrently or combined
- Target: < 30s end-to-end for typical image

---

## 13. Migration Plan (V1 → V2)

- Keep V1 entrypoints and files unchanged.
- V2 lives in `publisher_v2/` and uses separate Poetry env.
- Config compatibility layer reads existing INI + `.env`; warns if legacy env names used (`DROPBOX_APP_PASSWORD` → `DROPBOX_APP_SECRET`).
- CLI wrapper to support existing cron by pointing to new entrypoint.

---

## 14. Acceptance Criteria

- Setup with Poetry on Python 3.12; `make setup-dev` passes.
- `make run` posts to at least one enabled platform in debug mode without archiving.
- Archive moves to `archive/` when enabled and any platform succeeds (non-debug).
- Logs redact secrets; temp files are cleaned.
- Test suite passes with ≥80% coverage on core modules.

---

## 15. Risks and Mitigations

- Instagram via instagrapi may break or violate TOS → prefer Graph API adapter; guard with feature flag.
- External API cost/latency → cache model clients; rate limit; retries with backoff.
- Dropbox path assumptions → validate; handle root and nested folders; ensure archive exists.

---

## 16. Dependencies (minimums)

- dropbox >= 12
- openai >= 2.7
- replicate >= 1.0
- python-telegram-bot >= 20
- pillow >= 10
- python-dotenv >= 1.0
- pydantic >= 2.0
- tenacity >= 8.2
- cryptography >= 43
- pytest >= 8, pytest-asyncio, pytest-cov
- black, isort, flake8, mypy, pylint, safety, bandit

---

## 17. Command-line and Make targets

- `make install` → poetry install
- `make setup-dev` → hooks, examples, env
- `make run` → poetry run publisher_v2 (config path)
- `make auth` → poetry run auth (Dropbox PKCE refresh)
- `make check` → format, lint, types, tests, pre-commit

---

## 18. Future Work (Post-V2)

- Video support (ffmpeg), scheduling, analytics dashboard, A/B testing, Twitter/X, Facebook, LinkedIn adapters.


