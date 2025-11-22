<!-- docs_v2/08_Features/08_02_Feature_Design/015_cloud-storage-dropbox_design.md -->

# Design: Cloud Storage Adapter (Dropbox)

## 1. Summary
The `DropboxStorage` component adapts the generic `Storage` protocol to the Dropbox API v2. It provides robust, retry-enabled file operations including listing, downloading, uploading (sidecars), and moving (archiving). It serves as the persistent backbone of the application.

## 2. Context & Assumptions
- **Current State:** The system relies on `DropboxStorage` for all file I/O. Local storage is used only for temporary processing.
- **Constraints:** 
  - Must work with `dropbox` Python SDK.
  - Must handle `refresh_token` based authentication (long-lived).
  - Must operate within Dropbox API rate limits.
- **Assumptions:**
  - The Dropbox account has sufficient storage space.
  - The "Offline Access" token does not expire if used regularly.

## 3. Requirements
### Functional
- **List Images:** Return `.jpg`, `.jpeg`, `.png` files from a configured folder.
- **Metadata Dedup:** Return `content_hash` alongside filenames to allow avoiding redundant downloads.
- **Download:** Fetch file bytes securely.
- **Temp Link:** Provide time-limited URLs for OpenAI analysis (avoiding byte upload to OpenAI).
- **Archive:** Move files to an archive folder.
- **Sidecars:** Detect and move `.txt` sidecars alongside images.

### Non-Functional
- **Reliability:** Automatically retry on network failures (5xx, connection errors).
- **Security:** Never log the App Secret or Refresh Token.
- **Performance:** Use `files_list_folder` efficient pagination (though current implementation implies small folders < 2k files for simplicity).

## 4. Architecture & Design

### Class Structure
`DropboxStorage` implements the `Storage` protocol.

```python
class DropboxStorage:
    def __init__(self, config: DropboxConfig): ...
    async def list_images(self, folder: str) -> List[str]: ...
    async def list_images_with_hashes(self, folder: str) -> List[Tuple[str, str]]: ...
    async def download_image(self, folder: str, filename: str) -> bytes: ...
    async def get_temporary_link(self, folder: str, filename: str) -> str: ...
    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None: ...
    async def move_image_with_sidecars(self, folder: str, filename: str, target_subfolder: str) -> None: ...
```

### Authentication Flow
We use the **Offline Access** flow:
1.  Config provides `DROPBOX_APP_KEY`, `DROPBOX_APP_SECRET`, and a long-lived `refresh_token`.
2.  On instantiation, the `dropbox.Dropbox` client is initialized with these credentials.
3.  The SDK automatically refreshes the short-lived access token when it expires, handling the OAuth2 dance internally.

### Archive & Curation Logic
Archiving is implemented as a **Move** operation, not Copy+Delete.
- **Benefit:** Atomic on Dropbox side; preserves file ID/history; instant.
- **Sidecar Handling:**
  1. Construct path for `image.jpg`.
  2. Construct path for `image.txt`.
  3. Move image (autorename=True).
  4. Try to move sidecar (autorename=True). Ignore "Not Found" error if sidecar is missing.

## 5. Error Handling & Retries
We use the `tenacity` library to wrap all external calls.
- **Decorator:** `@retry(stop=stop_after_attempt(3), wait=wait_exponential(...))`
- **Exceptions:**
  - Catch `dropbox.exceptions.ApiError`.
  - Catch `dropbox.exceptions.AuthError` (critical, usually implies invalid token).
  - Wrap and re-raise as `publisher_v2.core.exceptions.StorageError` to decouple the core domain from Dropbox SDK details.
- **Edge Case:** "File not found" on optional sidecar downloads is caught and returned as `None` (cache miss), not an error.

## 6. Testing Strategy
- **Unit Tests:**
  - Mock `dropbox.Dropbox` client.
  - Simulate API responses (FileMetadata, ListFolderResult).
  - Simulate `ApiError` to verify retry logic and exception mapping.
- **Integration Tests:**
  - Use a "Live" test mode (optional/manual) against a real Dropbox sandbox folder to verify token refresh and API contracts.

## 7. Risks & Mitigations
- **Risk:** Dropbox API changes (v2 -> v3).
  - **Mitigation:** Isolate all API calls in this one adapter class.
- **Risk:** Archive folder gets too large.
  - **Mitigation:** Dropbox `list_folder` supports pagination; currently we don't list the archive, only the inbox.
