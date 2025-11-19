<!-- docs_v2/08_Features/08_04_ChangeRequests/005/002_mobile-image-size-optimization.md -->

# Mobile Image Size Optimization — Change Request

**Feature ID:** 005  
**Change ID:** 005-002  
**Name:** mobile-image-size-optimization  
**Status:** Proposed  
**Date:** 2025-11-19  
**Author:** Evert (maintainer)  
**Parent Feature Design:** docs_v2/08_Features/08_02_Feature_Design/005_web-interface-mvp_design.md  

## Summary
This change request refines the Web Interface MVP so that images are rendered in a bandwidth-efficient, mobile-friendly size. The goal is to reduce transferred bytes and improve perceived performance when using the web UI over mobile connections, without degrading the desktop experience. The change builds on the existing web UI image flow and NFRs by adding explicit behavior for responsive sizing and, where feasible, lower-resolution delivery.

## Problem Statement
Currently, the Web Interface MVP design does not specify how image size and resolution should be handled for mobile users on low-bandwidth connections. As a result, the UI may download and render full-resolution images even on small screens, consuming unnecessary bandwidth and causing slow loading or janky interactions. This creates friction for users who primarily review and publish content from their phones.

## Goals
- Reduce bandwidth usage for image viewing on mobile devices without altering the source images in Dropbox.  
- Improve perceived and actual load times for the main image view on typical mobile connections.  
- Preserve a good viewing experience on both mobile and desktop screens, with responsive, non-distorted image rendering.

## Non-Goals
- Introducing a new image CDN or persistent image cache beyond existing Dropbox-based storage.  
- Implementing complex multi-resolution or device-specific image negotiation beyond a simple, documented strategy.  
- Changing the underlying AI, captioning, or publishing flows defined in the Web Interface MVP.

## Affected Feature & Context
- **Parent Feature:** Web Interface MVP  
- **Relevant Sections:**  
  - §3. Requirements – NFR1 Performance, NFR6 Accessibility  
  - §5. Detailed Flow – Flow 1: User Opens Web UI  
  - §4. Architecture & Design – Proposed Architecture (FastAPI web app + Dropbox temp links)  
- The change fits within the existing architecture by refining how the web layer and frontend choose and render image URLs returned from Dropbox. It does not alter orchestrator behavior or storage semantics; instead, it adds constraints and guidance for image dimensions and responsive rendering in the web UI and, if needed, lightweight server-side support for size-aware URLs.

## User Stories
- As a mobile user viewing images over a limited data plan, I want the web UI to load appropriately sized versions of images so that pages load quickly and don’t consume unnecessary bandwidth.  
- As an operator reviewing images on both phone and desktop, I want the image to scale sensibly to my screen size so that I can see enough detail without needing full-resolution downloads on mobile.  
- As a maintainer, I want the optimization to reuse the existing Dropbox-based flow and be simple to test and operate.

## Acceptance Criteria (BDD-style)
- Given a user opens the web UI on a mobile device (viewport width ≤ 480px), when the initial image is loaded via `GET /api/images/random`, then the rendered image must fit within the viewport width without horizontal scrolling and must not exceed a configured maximum long-edge resolution (e.g., ≤ 1280px) in the rendered HTML/CSS.  
- Given a user repeatedly requests new images on a mobile device, when network conditions are typical for 3G/4G connections, then the time from tapping "Next Image" to seeing the image should meet or improve on the existing NFR1 performance target for `/api/images/random` and should not regress on desktop.  
- Given a user opens the same image on a desktop browser (viewport width ≥ 1024px), when the image is rendered, then it should still display at a visually reasonable size (not excessively small) while respecting a sensible maximum width to avoid unnecessary bandwidth usage.  
- Given the optimization is implemented, when viewing the UI on different screen sizes (phone, tablet, desktop), then images must maintain correct aspect ratio and not appear stretched or distorted.  
- Given the optimization is enabled, when the web UI is run in preview/staging environments, then tests or manual checks can verify the configured image dimension constraints without requiring changes to Dropbox or sidecar formats.

## UX / UI Requirements
- The main image display area must be fully responsive:  
  - On small viewports, the image width should be constrained to the viewport width (or container width) with `max-width: 100%` and an appropriate `height: auto` behavior.  
  - On larger screens, the image should not exceed a reasonable maximum width (e.g., a centered column) to avoid unnecessarily large renders.  
- The layout must avoid introducing horizontal scrolling while an image is displayed on typical phone resolutions.  
- Any loading indicators or buttons ("Next Image", "Analyze & Caption", "Publish") must remain visible and usable on small screens after this change.  
- Accessibility requirements from the parent design (e.g., alt text) must remain intact.

## Technical Notes & Constraints
- No new persistent storage or databases may be introduced; Dropbox remains the sole image and sidecar store as per the parent design.  
- The optimization should primarily rely on responsive frontend behavior (CSS/HTML) and, optionally, documented patterns for requesting smaller renditions from Dropbox if available, without changing the sidecar format.  
- The API contracts defined in §3 (e.g., `GET /api/images/random` → `ImageResponse`) should remain backward-compatible; any changes to image URL handling must preserve existing fields.  
- Any configuration for maximum rendered resolution or mobile-specific behavior should be additive (e.g., new optional config keys) and default-safe so that existing deployments are not broken.  
- The CLI workflows and non-web code paths must remain unchanged.

## Risks & Mitigations
- Over-aggressive downscaling could make images too small or blurry on some devices — Mitigation: use conservative default limits and validate visually on representative phones and desktops.  
- CSS-only changes might not sufficiently reduce bandwidth if full-resolution images are still fetched — Mitigation: where feasible, explore using Dropbox URL parameters or separate thumbnail URLs while keeping contracts backward-compatible.  
- Device and viewport detection logic could become brittle — Mitigation: base behavior primarily on responsive layout and container width, not on user-agent sniffing.

## Open Questions
- What exact maximum long-edge resolution and/or file size targets should we enforce for mobile vs. desktop? — Proposed answer: Start with a single max-rendered-width (e.g., 1280px) and refine based on testing.  
- Should the backend explicitly request lower-resolution images from Dropbox (if supported), or is CSS-based scaling sufficient for MVP? — Proposed answer: Prefer CSS-based scaling first; consider backend-assisted downscaling only if bandwidth metrics remain unsatisfactory.  
- Do we need a configuration flag to explicitly enable/disable mobile image optimization per deployment? — Proposed answer: TODO (decide based on early feedback and ops needs).


