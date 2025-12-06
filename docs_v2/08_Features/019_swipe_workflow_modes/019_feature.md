# Swipe Gestures & Workflow Modes

**ID:** 019
**Name:** swipe_workflow_modes
**Status:** Proposed
**Date:** 2025-12-06
**Author:** Evert

## Summary
The current web interface relies on a "Next Image" button and random image selection for all workflows. This feature introduces touch-friendly swipe gestures for mobile users and distinct "Publish" vs "Review" modes. "Publish" mode retains the existing random selection for curation, while "Review" mode enables sequential navigation (Next/Previous) through a sorted list of images, optimized for captioning and bulk review.

## Problem Statement
- **Mobile Friction:** Tapping a small "Next" button repeatedly is cumbersome on mobile devices; users expect swipe gestures.
- **Workflow Conflict:** The current random selection logic works well for "Publishing" (finding something new to post) but poorly for "Review/Captioning" (where a user wants to systematically go through images without missing any or seeing duplicates).
- **Navigation Limitations:** There is currently no way to go "back" to a previous image, which is critical when reviewing a batch.

## Goals
- **Mobile-First UX:** Implement swipe gestures (Left for Next, Right for Previous) on the image container.
- **Workflow Separation:** Introduce "Publish Mode" (Random, Next only) and "Review Mode" (Sorted, Next/Prev).
- **Zero-Build Frontend:** Implement gestures and logic using vanilla JavaScript without adding build steps or heavy libraries.
- **Backward Compatibility:** Retain existing "Next" button and random behavior as the default "Publish Mode".

## Non-Goals
- **Carousel Component:** We explicitly reject a heavy carousel/slider component to avoid complexity and pre-loading overhead.
- **Infinite Scroll:** We are not implementing a scrolling list view; the UI remains focused on single-image actions.
- **State Persistence:** We are not adding a database to track "read" status; "Review Mode" sorts by filename statelessly.

## Users & Stakeholders
- **Primary User:** Administrator/Content Creator using the web UI on a mobile device to curate and publish content.
- **Stakeholders:** Repository Maintainers (keeping code simple).

## User Stories
- As a mobile user, I want to swipe left on an image to load the next one, so that I can browse comfortably with one hand.
- As a content curator, I want to switch to "Review Mode", so that I can browse images in a predictable order (A-Z) and verify captions systematically.
- As a content curator, I want to swipe right (or click Previous) in Review Mode, so that I can re-check the image I just passed.
- As a user, I want visual feedback when I swipe, so that I know the app is responding.
- As an admin, I want the app to remember my last used mode, so I don't have to toggle it every time I reload.

## Acceptance Criteria (BDD-style)
- **Given** the web UI is open, **when** I swipe left on the image, **then** the next image loads (Random in Publish mode, Next Sorted in Review mode).
- **Given** "Publish Mode" is active (default), **when** I swipe right, **then** nothing happens (or it just loads another random image if decided), and there is no "Previous" action.
- **Given** I toggle to "Review Mode", **when** I navigate, **then** images appear in alphanumeric order by filename.
- **Given** "Review Mode" is active, **when** I swipe right or click Previous, **then** the immediately preceding image in the sorted list loads.
- **Given** any mode, **when** I swipe, **then** the image container slides/fades slightly to indicate the action before the new image loads.

## UX / Content Requirements
- **Gestures:**
  - Swipe Left: Next Image.
  - Swipe Right: Previous Image (Review Mode only).
- **Mode Toggle:** Segmented control or toggle switch clearly labeling "Publish" vs "Review".
- **Feedback:** CSS transition (transform/opacity) during swipe or on navigation trigger.
- **Position:** In Review Mode, show "Image X of Y" (optional/text-only) to indicate progress.

## Technical Constraints & Assumptions
- **No External JS Libraries:** Swipe detection must be implemented in vanilla JS (~30 lines).
- **Performance:** Review mode must not fetch full metadata for all images; likely need a lightweight list endpoint.
- **Dropbox:** Listing thousands of files might be slow; we assume the folder size is reasonable (<1000) or we accept initial load latency for Review Mode.
- **Session:** Mode preference stored in `localStorage`.

## Dependencies & Integrations
- **Dropbox API:** Used for listing files.
- **Existing Web Endpoints:** `/api/images/random` (to be augmented or complemented).

## Data Model / Schema
- No database changes.
- New API response shapes for list/sorted navigation.

## Security / Privacy / Compliance
- Standard auth applies.
- No new PII.

## Performance & SLOs
- Swipe reaction time < 100ms (visual).
- Next image load time matches existing P95 targets (cached thumbnails help here).
- Review mode list fetching < 2s.

## Observability
- Log mode switches.
- Log navigation actions with mode context (`web_next_image` vs `web_prev_image`, `mode=publish|review`).

## Risks & Mitigations
- **Risk:** Swipe interferes with scroll.
  - **Mitigation:** Vertical scroll allowed; swipe threshold (e.g., 50px horizontal) enforces intent.
- **Risk:** Review mode list stale.
  - **Mitigation:** Refresh list on mode switch; accept eventual consistency.

## Open Questions
- Should "Publish" mode allow swipe right?
  - *Answer:* No, or it treats it as "Next Random" (functionally same as swipe left). We will disable Swipe Right in Publish Mode to avoid confusion about "going back".

## Milestones
- **M1:** Frontend Gestures (works with current backend).
- **M2:** Backend Sorted Support + Mode Toggle.
- **M3:** Refinements (Position indicator, prefetching for sorted).

## Definition of Done
- Swipe gestures work on mobile (iOS/Android).
- Mode toggle switches behavior correctly.
- Review mode navigates A-Z.
- Previous button/gesture works in Review mode.
- Unit and Integration tests for new endpoints.

