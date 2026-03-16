# PUB-018: Thumbnail Preview Optimization

| Field | Value |
|-------|-------|
| **ID** | PUB-018 |
| **Category** | Web UI |
| **Priority** | INF |
| **Effort** | M |
| **Status** | Done |
| **Dependencies** | PUB-005, PUB-015 |

## Problem

Web interface image loading is painfully slow during curation workflows. Full-resolution images (5–20MB+) are served directly from Dropbox even when a small preview would suffice. On 4G, full images take 3–8 seconds; on 3G, ~64 seconds. This creates a curation bottleneck and wastes bandwidth—users only need a preview for most actions.

## Desired Outcome

Server-side thumbnail generation using Dropbox's native `files/get_thumbnail_v2` API. Display thumbnails (~50KB) by default for 100–150× faster loading. Preserve full-resolution access via explicit "View Full Size" / "Download" action. Target: image preview loads in <1 second on 4G; curation rate ~30 images/min vs ~4 before.

## Scope

- `get_thumbnail()` on `DropboxStorage` using Dropbox Thumbnail API (default w960h640)
- New endpoint `GET /api/images/{filename}/thumbnail` with optional `size` query param
- `ImageResponse` extended with `thumbnail_url`; `temp_url` retained for full-size
- Frontend: display thumbnail by default; "Download Full Size" button for explicit access
- Cache-Control headers (e.g., max-age=3600) on thumbnail responses

## Acceptance Criteria

- AC1: Image preview loads in <1 second on 4G mobile network
- AC2: Curation workflow (Keep/Remove) allows viewing 20+ images per minute
- AC3: Full-size image remains accessible via explicit user action
- AC4: No regression in existing functionality (analyze, publish, etc.)
- AC5: Mobile bandwidth usage reduced by 90%+

## Implementation Notes

- Dropbox `ThumbnailSize.w960h640`, `ThumbnailFormat.jpeg`, `ThumbnailMode.fitone_bestfit`
- No additional infrastructure; thumbnails generated on-demand by Dropbox
- Thumbnail URL served via our API for caching control; `temp_url` for direct Dropbox link

## Related

- [Original feature doc](../../08_Epics/002_web_admin_curation_ux/018_thumbnail_preview_optimization/018_feature.md) — full historical detail
