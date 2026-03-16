# PUB-030: Mastodon / Fediverse Publisher

| Field | Value |
|-------|-------|
| **ID** | PUB-030 |
| **Category** | Publishing |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Not Started |
| **Dependencies** | — |

## Problem

After FetLife and Telegram, the Fediverse is the most natural home for NSFW artistic and kink photography. Mastodon and compatible platforms (Pixelfed, Pleroma, Akkoma, Misskey) have a built-in content warning (CW) and sensitive media system designed specifically for this use case. Many NSFW-friendly instances exist where kink and art nude communities have settled since the Tumblr purge. Unlike mainstream platforms, the Fediverse has no corporate content policy — instance admins set the rules, and many explicitly welcome adult content.

The publisher has no Fediverse support. Adding it would reach a large, engaged audience that actively curates NSFW content and values proper CW etiquette.

## Desired Outcome

A `MastodonPublisher` implementing the `Publisher` interface that posts images with captions to any Mastodon-compatible instance. Posts are marked as sensitive with configurable content warnings. Because Mastodon's API is the de facto Fediverse standard, a single implementation covers Mastodon, Pixelfed, Pleroma, Akkoma, and other compatible platforms.

## Scope

- `MastodonPublisher` class in `publisher_v2/services/publishers/mastodon.py`
- Authentication via access token (OAuth app or personal access token)
- Two-step posting: upload media (`POST /api/v1/media`) → create status (`POST /api/v1/statuses`)
- Sensitive flag: posts marked `sensitive: true` by default
- Content warning (CW / spoiler text): configurable per instance (e.g., "NSFW", "artistic nude", "shibari")
- Alt text support via media `description` field (consumes `context["alt_text"]` from PUB-026 if available)
- Visibility control: configurable (`public`, `unlisted`, `private`, `direct`; default `unlisted`)
- `MastodonConfig` in config schema (instance_url, access_token, content_warning, visibility)
- `platforms.mastodon_enabled` flag
- `build_publishers()` factory updated to include Mastodon
- Orchestrator config: `publishers.mastodon` block with `credentials_ref` for access token
- `format_caption()` updated with Mastodon entry (500 char default limit, configurable per instance)
- Platform limits in `ai_prompts.yaml` static config

## Non-Goals

- No multi-instance posting (one instance per publisher config; multiple instances need multiple publisher entries)
- No federation management or follow/boost automation
- No direct message support
- No poll or thread support
- No instance-specific feature detection (assumes Mastodon-compatible API baseline)

## Acceptance Criteria

- AC1: `MastodonPublisher` implements `Publisher` with `platform_name = "mastodon"`
- AC2: Given valid credentials (instance URL + access token), when `publish()` is called, then an image post with caption appears on the Mastodon instance
- AC3: Media is uploaded via `POST /api/v1/media` with image bytes and alt text description
- AC4: Status is created via `POST /api/v1/statuses` with media attachment ID, caption text, sensitive flag, and spoiler text
- AC5: Posts are marked `sensitive: true` by default (configurable to `false` for SFW instances)
- AC6: Content warning text (`spoiler_text`) is configurable per instance (default: "NSFW")
- AC7: If `context["alt_text"]` is present, it is set as the media `description` (alt text)
- AC8: Post visibility is configurable: `public`, `unlisted`, `private`, `direct` (default: `unlisted`)
- AC9: Caption is truncated to the instance's character limit (default 500, configurable)
- AC10: When `platforms.mastodon_enabled` is false, the publisher is not called
- AC11: `build_publishers()` includes `MastodonPublisher` when config is available
- AC12: Authentication failure returns `PublishResult(success=False)` with a descriptive error, without blocking other publishers
- AC13: Transient errors (network, 5xx) are retried with exponential backoff (up to 3 attempts)
- AC14: The publisher works with Mastodon, Pixelfed, Pleroma, and other Mastodon-API-compatible instances
- AC15: No credentials (access token) appear in logs
- AC16: Orchestrator mode resolves Mastodon credentials via `/v1/credentials/resolve`
- AC17: Preview mode skips actual posting and logs what would be posted
- AC18: Web UI `/api/config/publishers` includes `mastodon_enabled` status

## Implementation Notes

- Use `httpx` (already a project dependency) for API calls — no need for a dedicated Mastodon library. The API is simple REST:
  - `POST /api/v1/media` with `multipart/form-data` (file, description) → returns `{ "id": "..." }`
  - `POST /api/v1/statuses` with JSON (status, media_ids, sensitive, spoiler_text, visibility) → returns status object
- Alternatively, `Mastodon.py` is a mature Python library but adds a dependency; raw `httpx` keeps it lighter
- Access tokens: created in instance Settings → Development → New Application (read+write scope) or generated per-user via OAuth
- Async: `httpx.AsyncClient` is natively async, no `asyncio.to_thread` needed
- Media processing: Mastodon accepts images up to 16MB; Pixelfed may vary. Pre-resize to max 1920px width for consistency.
- The 500-char limit is Mastodon's default but instances can configure higher limits (Pleroma often allows 5000+). Make the limit configurable via `mastodon.max_caption_length`.
- Content warning etiquette: in the Fediverse NSFW community, CWs are expected and respected. Posting without CW on NSFW content is considered rude. Default to `spoiler_text: "NSFW"` but allow customization (e.g., "shibari", "artistic nude", "bondage photography").
- Credential shape for orchestrator: `{ "instance_url": "https://mastodon.example", "access_token": "xxxx" }`
- Config shape: `mastodon.instance_url`, `mastodon.access_token`, `mastodon.content_warning`, `mastodon.visibility`, `mastodon.sensitive`, `mastodon.max_caption_length`
- For Pixelfed specifically: the same API works, but Pixelfed is image-first and may render posts differently. No special handling needed.

## Related

- [PUB-017: Multi-Platform Publishing](archive/PUB-017_multi-platform-publishing.md) — the publisher interface this implements
- [PUB-027: Bluesky Publisher](PUB-027_bluesky-publisher.md) — sibling new-platform item; different protocol but similar scope
- [PUB-026: AI Alt Text](PUB-026_ai-alt-text.md) — provides alt text consumed by this publisher via media description
- [PUB-025: Platform-Adaptive Captions](PUB-025_platform-adaptive-captions.md) — provides Mastodon-optimized captions
