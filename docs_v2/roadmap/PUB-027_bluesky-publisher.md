# PUB-027: Bluesky Publisher

| Field | Value |
|-------|-------|
| **ID** | PUB-027 |
| **Category** | Publishing |
| **Priority** | P1 |
| **Effort** | S |
| **Status** | Not Started |
| **Dependencies** | — |

## Problem

The publisher supports three platforms: Telegram, Instagram, and Email. Bluesky is a growing decentralized social network with an open API (AT Protocol) that requires no app review, no OAuth dance, and no rate-limit negotiation. It is the most accessible new platform to add, and its absence is a visible gap compared to 2026 scheduling tools that support 8+ platforms. The publisher architecture (PUB-017) was designed for exactly this: "Adding a new platform should only require adding a new class file."

## Desired Outcome

A `BlueskyPublisher` implementing the `Publisher` interface that posts images with captions to Bluesky. Authenticated via app password (no OAuth). Integrated into the publisher factory, orchestrator config, and web UI platform toggles.

## Scope

- `BlueskyPublisher` class in `publisher_v2/services/publishers/bluesky.py`
- Authentication via AT Protocol app password (handle + app password)
- Image upload as blob → post with embedded image and caption text
- Caption truncated to 300 chars (Bluesky limit)
- Alt text support via `image.alt` field (consumes `context["alt_text"]` from PUB-026 if available)
- Hashtag-to-tag conversion: extract `#hashtags` from caption and convert to Bluesky facet links
- `BlueskyConfig` in config schema (handle, app_password)
- `platforms.bluesky_enabled` flag
- `build_publishers()` factory updated to include Bluesky
- Orchestrator config: `publishers.bluesky` block with `credentials_ref` for app password
- `format_caption()` updated with Bluesky entry (300 char limit, hashtag-to-facet conversion)
- Platform limits in `ai_prompts.yaml` static config

## Non-Goals

- No thread/multi-post support (single image post only)
- No video support (Bluesky API doesn't support video via API yet)
- No reply or repost automation
- No DM or engagement features

## Acceptance Criteria

- AC1: `BlueskyPublisher` implements `Publisher` with `platform_name = "bluesky"`
- AC2: Given valid credentials (handle + app password), when `publish()` is called, then an image post with caption appears on the Bluesky account
- AC3: Caption is truncated to 300 characters by `format_caption()`
- AC4: If `context["alt_text"]` is present, it is set as the image alt text via `image.alt`
- AC5: Hashtags in the caption are converted to Bluesky facet links (clickable tags)
- AC6: When `platforms.bluesky_enabled` is false, the publisher is not called
- AC7: `build_publishers()` includes `BlueskyPublisher` when config is available
- AC8: Authentication failure returns `PublishResult(success=False)` with a descriptive error, without blocking other publishers
- AC9: Transient errors (network, 5xx) are retried with exponential backoff (up to 3 attempts)
- AC10: No credentials (app password, handle) appear in logs
- AC11: Orchestrator mode resolves Bluesky credentials via `/v1/credentials/resolve`
- AC12: Preview mode skips actual posting and logs what would be posted
- AC13: Web UI `/api/config/publishers` includes `bluesky_enabled` status

## Implementation Notes

- Use the `atproto` Python SDK (`pip install atproto`) for AT Protocol client
- Auth: `client.login(handle, app_password)` — session persists for the client lifetime
- Image upload: `client.upload_blob(image_bytes)` → blob ref → embed in post record
- Post: `client.send_post(text=caption, embed=image_embed)` with facets for hashtags/mentions
- Facets are byte-offset ranges in the caption text pointing to `app.bsky.richtext.facet` records
- Wrap all `atproto` calls in `asyncio.to_thread` (SDK is synchronous)
- App passwords are generated in Bluesky Settings → App Passwords (no OAuth app registration needed)
- Credential shape for orchestrator: `{ "handle": "user.bsky.social", "app_password": "xxxx-xxxx-xxxx-xxxx" }`

## Related

- [PUB-017: Multi-Platform Publishing](archive/PUB-017_multi-platform-publishing.md) — the publisher interface this implements
- [PUB-026: AI Alt Text](PUB-026_ai-alt-text.md) — provides alt text consumed by this publisher
- [PUB-025: Platform-Adaptive Captions](PUB-025_platform-adaptive-captions.md) — provides Bluesky-optimized captions
