# Mobile Image Size Optimization — Change Design

**Feature ID:** 005  
**Change ID:** 005-002  
**Parent Feature:** Web Interface MVP  
**Design Version:** 1.0  
**Date:** 2025-11-19  
**Status:** Design Review  
**Author:** Evert (maintainer)  
**Linked Change Request:** docs_v2/08_Epics/08_04_ChangeRequests/005/002_mobile-image-size-optimization.md  
**Parent Feature Design:** docs_v2/08_Epics/08_02_Feature_Design/005_web-interface-mvp_design.md  

## 1. Summary

- Problem & context (from Change Request + parent feature).
  - The Web Interface MVP currently serves and renders full-resolution Dropbox images without explicit guidance for mobile/low-bandwidth scenarios. On phones, this can mean unnecessary data transfer, slow loading, and janky interaction, even though the UI is explicitly meant to be mobile-friendly.
- Goals & Non-goals (scoped to this change).
  - Goals: Reduce effective bandwidth and improve perceived performance for mobile users by constraining rendered image size and, where reasonable, paving the way for smaller image variants—while preserving a good desktop experience and keeping all core image/AI/publish flows unchanged.
  - Non-goals: Introducing a new image CDN, changing Dropbox as the source of truth, altering sidecar formats, or modifying orchestrator/AI/publisher behavior.

## 2. Context & Assumptions

- Current behavior (only for affected parts).
  - `GET /api/images/random` returns an `ImageResponse` with a single `temp_url` (Dropbox temporary link) pointing to the original image.
  - The web UI (`index.html`) displays that `temp_url` directly in an `<img>` tag, with only basic responsiveness described (mobile-friendly viewport, touch buttons) but no explicit constraints on image dimensions or bandwidth use.
- Constraints inherited from the parent feature.
  - No new databases or persistent stores (§2. Context & Assumptions).
  - Dropbox and sidecars remain the source of truth (§3, §4).
  - Web UI must be mobile-friendly and touch-friendly (NFR6 Accessibility).
  - Contracts for `ImageResponse` and endpoints should remain backward-compatible.
- Dependencies (internal services, external APIs).
  - Internal: `publisher_v2.web.app` (FastAPI app), `publisher_v2.web.models.ImageResponse`, `publisher_v2.web.templates/index.html`, any existing CSS/JS for the Web UI.
  - External: Dropbox temp-link URLs as image source; browsers’ responsive layout behavior.
- Assumptions.
  - For this change, we prefer CSS/HTML-based responsive rendering first; backend-assisted lower-res variants are optional and must be strictly backward-compatible.
  - We can add small, optional web config fields (e.g., `WebConfig.max_image_width_px`) without impacting CLI flows.

## 3. Requirements

### 3.1 Functional Requirements

- **CR1:** The web UI must render images so that, on small mobile viewports, the image fits within the viewport/container width without horizontal scrolling and maintains correct aspect ratio.
- **CR2:** On desktop and tablet viewports, the image must be rendered within a sensible maximum width (to avoid needlessly huge displayed images) while remaining visually usable.
- **CR3:** The change must not alter API response shapes, sidecar formats, or orchestrator/AI/publisher semantics.
- **CR4:** (Optional, future-compatible) The design should allow, but not require, substituting a lower-resolution image URL in `ImageResponse.temp_url` via configuration or a small helper without breaking existing clients.

### 3.2 Non-Functional Requirements

- The change must **improve or at least maintain** current P95 latency targets for `/api/images/random` on typical mobile networks (NFR1 Performance).
- The UI must remain accessible: images must keep correct aspect ratio, alt text remains present, and buttons remain reachable on small screens (NFR6 Accessibility).
- No additional secrets or PII may be introduced; logs remain unchanged except for any optional new structured web events (not required for this change).
- The implementation must be backwards-compatible: existing deployments without new web configuration should behave correctly with conservative default sizing.

## 4. Architecture & Design (Delta)

### 4.1 Current vs. Proposed

- Current flow.
  - `/api/images/random` returns `ImageResponse` with `temp_url`.
  - `index.html` uses that `temp_url` directly inside an `<img>` element, with unspecified or minimal CSS, allowing the browser to render the full-resolution image as wide as the layout permits.
- Proposed flow.
  - Keep the API responses and Dropbox temp-link usage unchanged.
  - Update the Web UI template (`index.html`) and (if present) CSS so that:
    - The image is wrapped in a responsive container (e.g., `.image-wrapper`) constrained by a configurable max width.
    - The `<img>` uses `max-width: 100%; height: auto;` and is styled to prevent horizontal scrolling on small viewports.
  - Optionally introduce a **web config knob** (e.g., `WebConfig.max_image_width_px`) that only affects CSS layout (via an inline style or data attribute) or—if needed later—governs a small helper that may choose a smaller `temp_url` variant while preserving the existing field name and semantics.

### 4.2 Components & Responsibilities

- `publisher_v2.web.templates/index.html`
  - Changes:  
    - Add a dedicated container for the main image with responsive layout rules (e.g., max-width tied to viewport and/or config).
    - Ensure buttons and text layout adjust gracefully around the resized image.
- `publisher_v2.web.app` / `publisher_v2.web.models`
  - Changes:  
    - Optionally (if we add a config knob), read `WebConfig.max_image_width_px` and expose it to the template rendering context (without affecting API JSON responses).
- `config.schema.WebConfig` (if extended)
  - Changes:  
    - Add optional, non-breaking field(s) like `max_image_width_px: int = 1280`, scoped to the web UI only.

### 4.3 Data & Contracts

- API contracts.  
  - No changes to `ImageResponse` fields or endpoint paths/methods.
  - `temp_url` remains a direct image URL; any future lower-res variants must still conform to the same meaning (“URL to an image suitable for display”).
- Config.
  - Optional new field (proposed) in `WebConfig`:
    - `max_image_width_px: int = 1280` (assumption; value can be tuned).
  - If not specified, a sensible default is used and existing deployments continue to render correctly.
- Sidecar / state.
  - No changes to `.txt` sidecars, SHA256 state, or archive behavior.

### 4.4 Error Handling & Edge Cases

- If `WebConfig.max_image_width_px` is misconfigured (e.g., non-positive), fall back to a hard-coded safe default (e.g., 1280) rather than failing the app.
- Extremely tall or wide images:
  - Still constrained by `max-width: 100%` and container max width.
  - Height remains auto, so tall images may require vertical scrolling, which is acceptable.
- If CSS fails to load or is overridden, the browser may revert to full-width behavior; this is acceptable as a degraded mode but should be avoided by bundling the key styling inline or in a critical path.

### 4.5 Security, Privacy, Compliance

- No changes to authentication or authorization; web auth requirements from the parent design remain.
- No new secrets or identifiers are introduced.
- The change affects only presentation; no additional logging or data collection is required.

## 5. Detailed Flow

- Main success path (mobile user opening UI).
  1. User navigates to `/` on a mobile device.
  2. FastAPI serves `index.html`, which now includes a responsive image container and updated CSS rules.
  3. Frontend JS calls `GET /api/images/random` as before and receives an `ImageResponse` with `temp_url`.
  4. The `<img>` in the responsive container is assigned `src=temp_url`.
  5. CSS ensures the image scales to container width (`max-width: 100%`, `height: auto`), with the container itself constrained to the viewport width; no horizontal scroll is introduced.
- Desktop flow.
  1. User opens `/` on a desktop browser.
  2. `index.html` renders the same responsive container, but CSS applies a maximum width (e.g., 1280px or 80vw) and centers the image area.
  3. The image remains clear and reasonably sized without spanning ultra-wide resolutions unnecessarily.
- Config-based variant (if `max_image_width_px` added).
  1. App startup loads `WebConfig` and passes `max_image_width_px` into template context.
  2. Template sets an inline style or CSS variable (e.g., `--max-image-width`) to this value.
  3. CSS uses that variable to constrain the image container across devices.

## 6. Testing Strategy (for this Change)

- Unit / Template-level tests.
  - If template rendering is testable, verify that the rendered HTML for `/` contains:
    - The image wrapper element with appropriate class/id.
    - The `<img>` element with `style` or class that enforces `max-width: 100%; height: auto;`.
  - If `WebConfig.max_image_width_px` is added, test that:
    - A configured value is passed to the template.
    - Invalid values fall back to default.
- Integration tests (web endpoints).
  - `GET /`:
    - Returns 200 with HTML containing the responsive container and image element.
  - Optional visual/layout checks may be approximated by parsing styles or class names but will primarily be validated manually.
- E2E / manual checks mapped to acceptance criteria.
  - On a phone (or dev tools mobile viewport):
    - Open `/` and assert the image fits the viewport width with no horizontal scroll.
    - Trigger "Next Image" multiple times and ensure responsiveness is preserved and load time feels acceptable.
  - On a desktop:
    - Verify image does not explode to full ultra-wide width and remains centered and legible.
  - Confirm that AI analysis and publishing flows still work unchanged.

## 7. Risks & Alternatives

- Risks.
  - CSS changes could unintentionally affect other layout elements (buttons, text).
    - Mitigation: Scope new rules to a dedicated container class and avoid broad selectors.
  - Purely CSS-based resizing still downloads the full-resolution file.
    - Mitigation: Accept for this change; evaluate backend-assisted lower-res URLs later if mobile data usage remains a concern.
- Alternatives considered.
  - Backend downscaling or different Dropbox renditions.  
    - Rejected for this change to keep the scope small and avoid additional complexity/processing; left as a potential future enhancement if needed.
  - User-agent-based device detection and conditional behavior.  
    - Rejected to avoid brittle heuristics; responsive design is simpler and more robust.

## 8. Work Plan (Scoped)

- Add/adjust markup and CSS in `index.html` to introduce a responsive image wrapper and safe defaults for image sizing on mobile and desktop.
- If desired, extend `WebConfig` with an optional `max_image_width_px` field and expose it to the template context.
- Wire the new config (if added) into the template via a CSS variable or inline style.
- Add or update tests to verify the presence of the new container and classes/attributes in the rendered `/` response.
- Perform manual verification on mobile and desktop (or browser dev tools) to validate layout, scroll behavior, and perceived performance.

## 9. Open Questions

- Should we introduce `WebConfig.max_image_width_px` now, or hard-code a single default (e.g., 1280px) and add configurability later? — Proposed answer: Start with a hard-coded constant in CSS; add config only if we find a real need during operation.  
- Do we want to log any explicit “mobile-friendly image sizing” events (e.g., container width, config value) for observability? — Proposed answer: Likely not for this small change; rely on existing web logs and manual UX checks.


