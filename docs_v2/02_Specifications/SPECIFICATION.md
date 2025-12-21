# Implementation Specification — Social Media Publisher V2

Version: 2.0  
Last Updated: December 21, 2025

This document is the ground truth for implementation. An AI coder can build V2 using this spec alone.

## 1. Environment and Tooling
- Python 3.12
- **uv** (primary workflow; `uv run ...` for CLI/test commands)
- Poetry (supported; repository includes `pyproject.toml` / `poetry.lock`)
- Dev tools: black, isort, flake8, mypy, pylint, pytest(+asyncio,+cov), safety, bandit

## 2. Configuration
See CONFIGURATION.md for full schema. Validation is mandatory with pydantic v2. Required secrets via `.env`:
- DROPBOX_APP_KEY, DROPBOX_APP_SECRET, DROPBOX_REFRESH_TOKEN
- OPENAI_API_KEY (primary)
- Optional: TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL_ID, EMAIL_PASSWORD, INSTA_PASSWORD or Graph API creds
- Optional SMTP: SMTP_SERVER, SMTP_PORT (defaults: smtp.gmail.com:587)

INI example keys:
- [Dropbox] image_folder="/Folder/Sub"; archive="archive"
- [Content] hashtag_string="..."; archive=true; debug=false
- [openAI] vision_model="gpt-4o"; caption_model="gpt-4o-mini"; system_prompt="..."; role_prompt="..."
- [Email] caption_target="subject|body|both"; subject_mode="normal|private|avatar"; confirmation_to_sender=true; confirmation_tags_count=5
- [Instagram]/[Telegram]/[Email] sections as needed

## 3. Domain Models (pydantic)
- Image: filename, dropbox_path, sha256, temp_link, local_path
- ImageAnalysis: description, tags[list[str]], mood[str], nsfw[bool], safety_labels[list[str]]
- CaptionSpec: platform[str], style[str], hashtags[str], max_length[int]
- PublishResult: success[bool], platform[str], post_id[str|None], error[str|None]
- WorkflowResult: success[bool], image_name[str], caption[str], results[dict[str, PublishResult]], archived[bool]

## 4. Interfaces
Storage (Protocol):
- async list_images(folder: str) -> list[str]
- async download_image(folder: str, filename: str) -> bytes
- async get_temporary_link(folder: str, filename: str) -> str
- async archive_image(folder: str, filename: str, archive_folder: str) -> None

AI (OpenAI only):
- class VisionAnalyzerOpenAI: async analyze(url_or_bytes: str|bytes) -> ImageAnalysis
- class CaptionGeneratorOpenAI: async generate(analysis: ImageAnalysis, spec: CaptionSpec) -> str
- class AIService: async create_caption(url_or_bytes: str|bytes, spec: CaptionSpec) -> str

Publishers:
- abstract Publisher:
  - property platform_name: str
  - def is_enabled() -> bool
  - async def publish(image_path: str, caption: str, context: dict | None = None) -> PublishResult

## 5. Adapters
DropboxStorage:
- Use refresh token + app key/secret
- Ensure archive folder exists (`files_create_folder_v2` ignore “already exists”)
- Compute sha256 of bytes on first download; use to prevent duplicates (optional cache JSON)

OpenAI Vision Analyzer:
- Use Chat Completions or Responses API with vision input
- Prompt for: concise scene description, entities, tags, mood, safety/nsfw
- Output mapped to ImageAnalysis

OpenAI Caption Generator:
- Input: ImageAnalysis, style, hashtags, platform limits
- Produce caption with style rules (see AI_PROMPTS_AND_MODELS.md)
- Respect platform length; trim and append hashtags; never exceed constraints

Replicate / other providers:
- Not used in V2. All AI tasks are fulfilled by OpenAI as MaaS.

InstagramPublisher:
- Preferred: Graph API; else instagrapi behind a feature flag
- Ensure image conforms to aspect/size limits (use Pillow to adjust/crop if needed)

TelegramPublisher:
- python-telegram-bot 20+, async send_photo

EmailPublisher:
- SMTP with STARTTLS; attach image
- FetLife behavior:
  - Caption placement via `caption_target` (subject|body|both)
  - Subject prefix via `subject_mode` (“Private: ” | “Avatar: ” | none)
  - Hashtags stripped; punctuation normalized for FetLife; length capped ≤ 240
  - Optional confirmation email to sender including N descriptive tags derived from vision analysis

## 6. Orchestrator
WorkflowOrchestrator.execute():
1) Validate config; initialize adapters; create correlation_id  
2) Select image: list images; skip archived; dedup via sha256 cache; choose by strategy (random/oldest)  
3) Acquire image: download to secure temp file (0600) and get temporary link; cleanup on finally  
4) Analyze: VisionAnalyzer.analyze(temp_link or bytes)  
5) Caption: Separate calls: VisionAnalyzer.analyze(...) then CaptionGenerator.generate(...) with platform‑aware spec  
6) Publish: run enabled publishers in parallel; collect results  
7) Archive: if any success and not debug → archive_image(...)  
8) Return WorkflowResult; log structured summary

## 7. Reliability
- Retries with tenacity on network/transient errors (OpenAI, Dropbox, SMTP, Telegram)
- Async rate limiter per service (e.g., OpenAI 20 rpm conservative default)
- Timeout for external calls; fail gracefully

## 8. Security
- Secrets from `.env`, never logged; logging redaction for key patterns (`sk-`, `r8_`, tokens)
- Session files encrypted at rest where feasible; otherwise ignored from VCS
- Temp files deleted in finally blocks; optional secure overwrite for sensitive contexts

## 9. CLI
Entrypoint:
- `uv run publisher_v2 --config path/to.ini [--debug] [--select filename] [--dry-publish] [--preview]`

## 10. Testing
- Unit: config loader/validator, prompt builders, caption post‑processor
- Integration: adapters with HTTP mocked
- E2E: orchestrator with staged mocks; assert archive decision and result aggregation
- Coverage target: 80%+

## 11. Acceptance Tests (must pass)
- Generates non‑empty caption for a valid image with debug on
- Respects per‑platform length constraints (truncate with ellipsis when required)
- Archives only when any platform succeeded and not in debug
- Redacts secrets in logs


