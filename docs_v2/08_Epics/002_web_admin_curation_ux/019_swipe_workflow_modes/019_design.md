# Swipe Gestures & Workflow Modes — Feature Design

**Feature ID:** 019
**Design Version:** 1.1
**Date:** 2025-12-06
**Status:** Approved
**Author:** Evert
**Feature Request:** 019_feature.md

## 1. Summary
This feature enhances the web interface by adding mobile-friendly swipe gestures and two distinct workflow modes: **Publish Mode** (existing random behavior) and **Review Mode** (new sequential A-Z behavior). It aims to improve mobile ergonomics and support systematic captioning/review workflows without introducing heavy frontend frameworks.

## 2. Context & Assumptions
- **Current State:** The Web MVP (Feature 005) supports random image loading only. Thumbnails (Feature 018) are optimized.
- **Constraint:** Vanilla JavaScript only; no build pipeline.
- **Constraint:** No database; Dropbox is the source of truth.
- **Assumption:** Image folder size is manageable for a simple sorted list approach (hundreds, not millions).

## 3. Requirements

### 3.1 Functional Requirements
- **FR1:** Detect touch swipe gestures (Left/Right) on the image container.
- **FR2:** Provide a UI toggle between "Publish" (Random) and "Review" (Sorted) modes.
- **FR3:** In **Publish Mode**, Swipe Left loads a random image. Swipe Right is disabled or no-op.
- **FR4:** In **Review Mode**, Swipe Left loads the next image alphabetically; Swipe Right loads the previous image.
- **FR5:** Implement backend support for sequential navigation (List or Next/Prev cursor).
- **FR6:** Persist user's mode choice in browser storage.

### 3.2 Non-Functional Requirements
- **NFR1:** **Responsiveness:** Visual feedback for swipes should be immediate (<50ms).
- **NFR2:** **Performance:** Review mode initialization should not block the UI for >2s.
- **NFR3:** **Simplicity:** No external JS libraries for gestures.

## 4. Architecture & Design

### 4.1 Proposed Architecture
The solution involves extending the `WebImageService` to handle sorted listings and modifying the frontend `index.html` to handle touch events and state.

```
[Browser / index.html]
      │
      ├── Gestures (TouchStart/End) -> JS Logic
      ├── Mode Toggle -> LocalStorage + JS Logic
      │
      ▼
[FastAPI / web/app.py]
      │
      ├── GET /api/images/random (Publish Mode)
      ├── GET /api/images/list (Review Mode - returns sorted filenames)
      │
      ▼
[WebImageService]
      │
      └── DropboxStorage (list_folder)
```

### 4.2 Components & Responsibilities

#### Frontend (`index.html`)
- **Swipe Handler:** Captures `touchstart` and `touchend`. Calculates delta X. triggers `handleNext()` or `handlePrev()`.
- **Mode Manager:** Toggles UI state (`isReviewMode`), updates button visibility (Prev button hidden in Publish), and calls appropriate API endpoints.
- **State:** Tracks current image index locally when in Review Mode (using the list fetched from backend).
- **Prefetching:** In Review Mode, automatically prefetch the next image in the sequence (index + 1) to reduce latency.

#### Backend (`publisher_v2.web`)
- **`GET /api/images/list`:** Returns a lightweight list of all image filenames in the folder, sorted A-Z.
  - **Filtering Consistency:** Must use `publisher_v2.utils.images` filters to ensure the list matches exactly what the random picker sees (same extensions, ignoring sidecars).
  - **Caching:** Cache this list in memory with a simple TTL (e.g., 60s) to avoid hitting Dropbox API on every mode toggle.
- **Shared Logic:** Refactor `WebImageService` to extract a private `_build_image_response(filename)` method. Both `get_random_image` and the new `get_image_details` must use this single source of truth to ensure consistency in response shapes, thumbnails, and sidecar handling.

### 4.3 Data Model / Schemas

**New Response: ImageListResponse**
```python
class ImageListResponse(BaseModel):
    filenames: list[str]  # Sorted A-Z
    count: int
```

### 4.4 API/Contracts

1.  **`GET /api/images/list`**
    - Returns: `{"filenames": ["a.jpg", "b.jpg", ...], "count": 2}`
    - Used by: Review Mode initialization.

2.  **`GET /api/images/{filename}`**
    - **New Endpoint:** Returns `ImageResponse` for a specific known file.
    - **Route Ordering:** Must be defined **after** `/api/images/random` and `/api/images/list` in FastAPI to prevent routing collisions (since `{filename}` would match "random" or "list" otherwise).
    - **Encoding:** Filenames must be URL-encoded in the path.

### 4.5 Error Handling
- If a file in the cached list is deleted, `GET /api/images/{filename}` returns 404. Frontend should handle this by automatically trying the next one or showing an error.

## 5. Detailed Flow

### Review Mode Flow
1. User toggles "Review Mode".
2. Frontend calls `GET /api/images/list`.
3. Backend lists Dropbox folder, filters using shared utilities, sorts, caches result, and returns list.
4. Frontend stores list `['img1.jpg', 'img2.jpg', ...]`.
5. Frontend determines current image index (if currently viewing one) or starts at 0.
6. Frontend calls `GET /api/images/{filename}` for the current image to display.
7. User Swipes Left (Next).
8. Frontend increments index.
9. Frontend calls `GET /api/images/{next_filename}`.

### Publish Mode Flow (Existing)
1. User toggles "Publish Mode".
2. User Swipes Left (Next).
3. Frontend calls `GET /api/images/random`.
4. Backend returns random image data using shared `_build_image_response` logic.

## 6. Rollout & Ops
- **Config:** None required. Feature is purely additive to UI.
- **Monitoring:** Log `web_mode_toggle` events.

## 7. Testing Strategy
- **Unit:** Test `get_sorted_images` in service. Test new endpoints. Ensure filtering matches random selection.
- **Integration:** Verify `/api/images/list` returns sorted list. Verify specific image retrieval works. Verify route precedence (random vs specific).
- **UX:** Manual test of swipe sensitivity and mode switching on mobile.

## 8. Risks & Alternatives
- **Risk:** Large folder size (>10k images).
  - *Mitigation:* The list payload becomes large.
  - *Alternative:* Pagination. For MVP/Feature 019, full list is acceptable as per "manageable folder size" assumption.
- **Risk:** Concurrency (images added/removed).
  - *Mitigation:* Client list might get stale. 404 handling handles "removed". "Added" images won't appear until list refresh (toggle mode or reload). Acceptable for MVP.

## 9. Work Plan
- **Story 01: Swipe Gestures (Frontend)** - Implement swipe detection and apply to current "Random" button logic.
- **Story 02: Backend Support** - Implement `GET /api/images/list` and `GET /api/images/{filename}`. Refactor shared logic.
- **Story 03: Mode Toggle & Integration** - Implement UI toggle and wiring to new backend endpoints.
- **Story 04: Position Indicator** - Add "X / Y" display in Review Mode.

## 10. Derived Stories
- **Story 01:** Swipe Gestures — Implement touch handlers and visual feedback.
- **Story 02:** Backend Support — Add list and specific-image endpoints. Refactor DRY logic.
- **Story 03:** Mode Toggle Integration — Add UI toggle and Review Mode logic.
- **Story 04:** Position Indicator — Add progress display for Review Mode.
