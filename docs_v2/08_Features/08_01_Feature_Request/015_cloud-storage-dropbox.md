<!-- docs_v2/08_Features/08_01_Feature_Request/015_cloud-storage-dropbox.md -->

# Cloud Storage Adapter (Dropbox)

**ID:** 015  
**Name:** cloud-storage-dropbox  
**Status:** Implemented  
**Date:** 2025-11-22  
**Author:** Retroactive Documentation  

## Summary
The system requires a remote, persistent source of truth for images and archives to support stateless deployment (e.g., Heroku) and multi-device workflows. This feature implements the `DropboxStorage` adapter, which handles authentication, downloading, metadata extraction for de-duplication, and atomic server-side moves for archiving and curation.

## Problem Statement
Running the publisher with local file storage is insufficient for a production workflow because:
1.  **State Persistence:** Archives must survive application restarts/redeploys. On ephemeral platforms like Heroku, local files are lost on restart.
2.  **Access:** The source folder is often shared with other devices/users (e.g., phone uploads) who add new content asynchronously.
3.  **Atomicity:** Moving an image to "Archive" must be a safe, atomic operation to prevent double-posting or data loss during race conditions.
4.  **De-duplication:** Downloading every image to hash it locally is bandwidth-inefficient; we need to leverage remote metadata.

## Goals
- **Remote Source of Truth:** Use Dropbox as the definitive file store for both inbox (pending) and archive (posted) images.
- **Robustness:** Handle transient network errors, rate limits, and token expiration automatically without operator intervention.
- **Efficiency:** Use Dropbox `content_hash` for de-duplication to avoid downloading duplicate files.
- **Sidecar Support:** Treat `.txt` sidecars as first-class citizens that move alongside images during archive/curation.

## Non-Goals
- **Multi-Provider Support:** Implementing S3, Google Drive, or Azure Blob Storage is out of scope for V2 (YAGNI).
- **Two-Way Sync:** The system is a consumer (read-move), not a synchronization engine. It does not push local changes back to Dropbox except for sidecar metadata.
- **UI for File Management:** No web UI for browsing Dropbox; file management is done via the Dropbox native client/web.

## Users & Stakeholders
- **Operators:** Who upload photos via their phone/desktop to a shared Dropbox folder.
- **Developers:** Who need a consistent `Storage` interface for testing and future expansion.
- **Maintenance Team:** Who need reliable archiving to verify what was posted.

## User Stories
- As an operator, I want to add photos to a Dropbox folder from my phone and have the bot pick them up automatically.
- As an operator, I want processed images to be moved to an `archive` subfolder so I can see what has been posted and keep the inbox clean.
- As a developer, I want the system to recover from temporary Dropbox API outages (5xx errors) by retrying, rather than crashing the workflow.
- As a curator, when I "Keep" or "Remove" an image, I want the associated caption text file to move with it.

## Acceptance Criteria (BDD-style)
- **Given** a valid `refresh_token` in configuration, **when** the access token expires, **then** the adapter must automatically refresh it and complete the request.
- **Given** an image `photo.jpg` and its sidecar `photo.txt` in the source folder, **when** `archive_image` is called, **then** both files must be moved to the `archive/` folder atomically (or quasi-atomically).
- **Given** a network failure (e.g., 503 Service Unavailable), **when** a storage operation is attempted, **then** the system must retry with exponential backoff up to a limit before failing.
- **Given** a list of files in Dropbox, **when** `list_images_with_hashes` is called, **then** it must return the filenames and their Dropbox-native `content_hash` for de-duplication.

## Technical Constraints & Assumptions
- **SDK:** Must use the official `dropbox` Python SDK (v11+).
- **Python:** Must be compatible with Python 3.9+.
- **Permissions:** Requires an App Key/Secret with "Offline Access" and "Files.Content.Write" permissions.
- **Environment:** Secrets (`DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, `DROPBOX_REFRESH_TOKEN`) must be loaded from environment variables, not checked into code.

## Dependencies & Integrations
- **Dropbox API v2:** The core external dependency.
- **Tenacity:** For retry logic.
- **Config Loader:** To supply credentials.
- **Workflow Orchestrator:** The primary consumer of this adapter.

## Risks & Mitigations
- **Risk:** Token expiry breaks production.  
  **Mitigation:** Use "Offline Access" (Refresh Token) flow which is valid indefinitely until revoked.
- **Risk:** Rate limiting by Dropbox.  
  **Mitigation:** The `tenacity` retry strategy includes exponential backoff.
- **Risk:** "File not found" race conditions (file deleted by user while bot is running).  
  **Mitigation:** Specific exception handling for 404s where appropriate (e.g., ignoring missing sidecars).
