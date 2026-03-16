# PUB-019: Swipe Gestures & Workflow Modes

| Field | Value |
|-------|-------|
| **ID** | PUB-019 |
| **Category** | Web UI |
| **Priority** | INF |
| **Effort** | L |
| **Status** | Done |
| **Dependencies** | PUB-005, PUB-010 |

## Problem

Tapping a small "Next" button repeatedly is cumbersome on mobile. The current random selection works for "Publishing" (finding something new to post) but poorly for "Review/Captioning" (systematic pass through images without missing any or seeing duplicates). There is no way to go "back" to a previous image when reviewing a batch.

## Desired Outcome

Touch-friendly swipe gestures (Left for Next, Right for Previous) on the image container. Distinct "Publish Mode" (Random, Next only) and "Review Mode" (Sorted A–Z, Next/Prev). Vanilla JavaScript implementation without build steps or heavy libraries. Retain existing "Next" button and random behavior as default "Publish Mode".

## Scope

- Swipe Left: Next image (Random in Publish mode, Next Sorted in Review mode)
- Swipe Right: Previous image (Review mode only; disabled in Publish mode)
- Mode toggle: "Publish" vs "Review" (segmented control or toggle)
- Review mode: lightweight list endpoint; images in alphanumeric order by filename
- Mode preference stored in `localStorage`
- Visual feedback (CSS transition) during swipe/navigation
- Optional "Image X of Y" position indicator in Review mode

## Acceptance Criteria

- AC1: Given the web UI is open, when I swipe left on the image, then the next image loads (Random in Publish mode, Next Sorted in Review mode)
- AC2: Given "Publish Mode" is active (default), when I swipe right, then nothing happens; there is no "Previous" action
- AC3: Given I toggle to "Review Mode", when I navigate, then images appear in alphanumeric order by filename
- AC4: Given "Review Mode" is active, when I swipe right or click Previous, then the immediately preceding image in the sorted list loads
- AC5: Given any mode, when I swipe, then the image container slides/fades slightly to indicate the action before the new image loads

## Implementation Notes

- Vanilla JS swipe detection (~30 lines); no external libraries
- Swipe threshold (e.g., 50px horizontal) to avoid scroll interference
- Review mode list fetched on mode switch; accept eventual consistency for list staleness
- Swipe reaction time <100ms (visual); list fetch <2s

## Related

- [Original feature doc](../../08_Epics/002_web_admin_curation_ux/019_swipe_workflow_modes/019_feature.md) — full historical detail
