# PUB-015: Cloud Storage Adapter (Dropbox)

| Field | Value |
|-------|-------|
| **ID** | PUB-015 |
| **Category** | Storage |
| **Priority** | INF |
| **Effort** | M |
| **Status** | Done |
| **Dependencies** | — |

## Problem

Running the publisher with local file storage is insufficient for production. Archives must survive application restarts/redeploys; on ephemeral platforms like Heroku, local files are lost. The source folder is often shared with other devices (e.g., phone uploads) adding content asynchronously. Moving an image to "Archive" must be atomic to prevent double-posting or data loss. Downloading every image to hash it locally is bandwidth-inefficient; we need to leverage remote metadata.

## Desired Outcome

Use Dropbox as the definitive file store for both inbox and archive images. Handle transient network errors, rate limits, and token expiration automatically. Use Dropbox `content_hash` for de-duplication to avoid downloading duplicate files. Treat `.txt` sidecars as first-class citizens that move alongside images during archive/curation.

## Scope

- `DropboxStorage` adapter with authentication, download, metadata extraction, atomic server-side moves
- Token refresh via "Offline Access" (Refresh Token) flow
- Retry with exponential backoff for 5xx/transient errors
- `list_images_with_hashes` returning Dropbox-native `content_hash`
- Sidecar `.txt` files moved atomically (or quasi-atomically) with images on archive

## Acceptance Criteria

- AC1: Given a valid `refresh_token` in configuration, when the access token expires, then the adapter must automatically refresh it and complete the request
- AC2: Given an image `photo.jpg` and its sidecar `photo.txt` in the source folder, when `archive_image` is called, then both files must be moved to the `archive/` folder atomically (or quasi-atomically)
- AC3: Given a network failure (e.g., 503 Service Unavailable), when a storage operation is attempted, then the system must retry with exponential backoff up to a limit before failing
- AC4: Given a list of files in Dropbox, when `list_images_with_hashes` is called, then it must return the filenames and their Dropbox-native `content_hash` for de-duplication

## Implementation Notes

- Official `dropbox` Python SDK (v11+); Tenacity for retry logic
- Secrets (`DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`) from environment only
- App permissions: "Offline Access" and "Files.Content.Write"
- 404 handling for files deleted by user while bot is running (e.g., ignore missing sidecars)

## Related

- [Original feature doc](../../08_Epics/000_v2_foundation/015_cloud_storage_dropbox/015_feature.md) — full historical detail
