<!-- docs_v2/08_Features/08_04_ChangeRequests/005/003_web-ui-admin-visibility-responsive-layout.md -->

# Web UI Admin Visibility & Responsive Layout — Change Request

**Feature ID:** 005  
**Change ID:** 005-003  
**Name:** web-ui-admin-visibility-responsive-layout  
**Status:** Proposed  
**Date:** 2025-11-20  
**Author:** Evert  
**Parent Feature Design:** docs_v2/08_Features/08_02_Feature_Design/005_web-interface-mvp_design.md  

## Summary
This change refines the Web Interface MVP UI to be fully responsive and to more clearly separate admin-only controls from general viewing functionality. It introduces an explicit admin login flow via a modal, hides admin and status sections when not authenticated, and converts the existing status display into a dedicated "Activity" area that focuses on the current action only. Analyze/Caption and Publish actions become truly admin-only (hidden when logged out), while the admin button behavior and labeling are updated to reflect login/logout state, and the background switches to a dark red theme when in admin mode. Admin sessions are explicitly short-lived (maximum of one hour) to reduce risk if a session is left unattended.

## Problem Statement
The current web UI does not clearly distinguish between admin-only actions and general viewing, leading to disabled-but-visible buttons and status sections that can confuse non-admin users. Additionally, the layout is not yet optimized for responsive, mobile-first usage, and there is no strong visual indication of being in admin mode, which can be risky if an interface is left open. Without clearer visibility rules, a focused Activity area, a short-lived admin session, and a distinct admin-mode background, the interface is harder to use on phones and less safe from accidental or unnoticed access to admin capabilities.

## Goals
- Make the web UI responsive and mobile-friendly across common viewport sizes.
- Restrict admin and status/administration sections to authenticated admin users only, with admin sessions lasting no longer than one hour.
- Provide a clear, modal-based admin login flow and intuitive login/logout button behavior, with a strong dark red visual theme when in admin mode.
- Present status and activity messages in a dedicated "Activity" section that shows only the current/most recent action so users understand what they are waiting for.

## Non-Goals
- Introducing new authentication mechanisms beyond what is already planned (e.g., no new auth backends or RBAC systems).
- Changing underlying publishing or analysis workflows, AI prompts, or storage behavior.
- Modifying CLI behavior or adding any new server-side persistence or databases.
- Implementing multi-user roles or granular permissions beyond a single admin/not-admin distinction.

## Affected Feature & Context
- **Parent Feature:** Web Interface MVP  
- **Relevant Sections:**
  - §3. Requirements – FR1 (Web UI Root Endpoint), FR3 (AI Analysis & Caption Generation), FR4 (Publishing)
  - §4. Architecture & Design – Components (`publisher_v2.web.app`, templates) and UI behavior
  - §5. Detailed Flow – Web UI interactions for opening the UI, analyzing, and publishing
  - Related change requests: `005-001_web-interface-admin-controls`, `005-002_mobile-image-size-optimization`
- This change builds on the existing FastAPI-based web layer and UI template by refining visibility rules, layout behavior, admin session handling, and visual cues. It leverages the same admin-auth concept and helpers introduced in earlier admin-control work (e.g., `web_admin_pw`, `pv2_admin` cookie, `/api/admin/login`, `/api/admin/status`, `/api/admin/logout`) and focuses on front-end rendering logic, modal flows, a maximum one-hour admin session, a dark red admin background, and a streamlined Activity section that emphasizes the current action, without altering backend orchestrator or storage contracts.

## User Stories
- As an admin, I want to log in via a simple modal and see admin-only controls appear, so that I can safely analyze, caption, and publish content from any device.
- As an admin, I want a clear visual indication (dark red background) when I am in admin mode, so that I immediately recognize when the interface has elevated capabilities.
- As a non-admin viewer (or logged-out user), I want to view images without seeing confusing disabled admin buttons, so that the interface feels clean and clear.
- As an admin, I want a clear logout control and an automatically short-lived session (≤1 hour), so that the interface is secured even if I forget to log out.
- As a user, I want the Activity section to show me only the current action and its progress/result, so that I know what I’m waiting for without being overwhelmed by history.
- As a mobile user, I want the UI to adapt to my screen size, so that I can comfortably use the interface on my phone without horizontal scrolling.

## Acceptance Criteria (BDD-style)
- Given a user is not logged in as admin, when they open the web UI, then the admin section and status/administration section are not rendered, the Analyze & Caption and Publish buttons are not shown, and only general viewing controls (e.g., Next Image) are visible.
- Given a user is not logged in as admin, when they tap the admin button in the top-left, then an admin password (or credential) challenge appears as a modal overlay, and closing or failing the challenge leaves admin-only sections hidden and the background in the normal (non-admin) theme.
- Given the admin successfully completes the modal login challenge, when the page updates, then the admin and status/administration sections become visible, the Analyze & Caption and Publish buttons are visible and enabled, the top-right administration button clearly indicates it acts as "Logout", and the page background switches to a dark red admin-mode theme.
- Given an admin is logged in, when they click the top-right logout button, then their admin session is cleared, admin and status/administration sections are hidden again, Analyze & Caption and Publish buttons are hidden, the background returns to the normal (non-admin) theme, and the UI returns to the non-admin state.
- Given an admin has been logged in for one hour or more since the last successful authentication, when they next interact with any admin-only action or endpoint, then they are treated as logged out (admin session expired), admin-only UI elements are hidden or disabled appropriately, and the admin modal is required again for further admin actions.
- Given any user triggers an action (e.g., Analyze & Caption, Publish), when that action starts and completes, then the Activity section displays only the current or most recent action and its state (e.g., "Analyzing…", "Analysis complete", "Publishing…", "Publish complete"), and prior actions are not shown as a long history.
- Given any user is using a mobile or narrow viewport (e.g., width ≤ 768px), when they load or interact with the UI, then layout and controls adapt responsively (no horizontal scroll needed for core actions, touch-friendly buttons, image and Activity sections stacked appropriately).

## UX / UI Requirements
- The main page layout must be responsive, with image display, controls, admin panels, and the Activity section adapting to various viewport widths (desktop, tablet, mobile) without requiring horizontal scrolling for core functionality.
- The admin button in the top-left opens a modal dialog for admin login; this modal clearly indicates it is an admin-only area, includes necessary input(s), and has accessible close/cancel behavior on both desktop and mobile.
- When the admin is logged in, the top-right administration button must be relabeled or visually updated to clearly signal a logout action (e.g., "Logout", "Admin Logout") and should be easily discoverable on both desktop and mobile.
- When admin mode is active, the overall page background (or clearly dominant page region) switches to a dark red theme that contrasts with the non-admin state, while preserving sufficient contrast and readability for text and controls.
- The admin section and status/administration section are only rendered when admin is logged in; they should not appear in a disabled or greyed-out state for non-admin users.
- The Analyze & Caption and Publish buttons must be entirely hidden when the user is not logged in as admin and must be fully visible and clearly actionable when admin is logged in.
- Status and progress messages must be displayed in a dedicated "Activity" section, visually distinct from the admin controls and main image area, and this section should show only the current/most recent action and its state; layout must remain readable on small screens (e.g., stacked layout, adequate spacing, and contrast).

## Technical Notes & Constraints
- No new backend persistence layers or data stores may be introduced; admin session handling must remain compatible with the stateless design described in the parent feature (e.g., token/cookie-based, with server-side enforcement of a maximum one-hour validity for admin authentication via the existing `pv2_admin` cookie TTL and `WEB_ADMIN_COOKIE_TTL_SECONDS`).
- The change should be implemented using the existing FastAPI app and template structure in `publisher_v2.web`, updating HTML/CSS/JS to enforce visibility, admin session timeout behavior (via backend checks and `/api/admin/status`/401–403 responses), responsive layout, dark red admin background, and Activity-section behavior while reusing current endpoints and services (no new SPA framework or JS build pipeline).
- CLI behavior and contracts defined for `publisher_v2.app` must remain unchanged.
- Any additional client-side logic for handling admin state and modal behavior must not leak secrets and should respect existing security assumptions (e.g., real authentication still validated server-side via `require_auth` and `require_admin`, no hard-coded passwords in the frontend, admin modal as an extra UI guard rather than a replacement for HTTP auth).
- Styling changes should be mobile-first and consistent with existing color/typography choices, using a dark red palette for admin mode that maintains accessibility standards (contrast ratios, legible text); the chosen colors should meet at least WCAG AA contrast ratios for all text and controls in admin mode.
- The Activity section should be implemented so that each new action overwrites or replaces the previous entry rather than accumulating a long list, and individual messages should be self-contained and clearly describe the current operation (e.g., “Publish failed after successful analysis: …”); if longer history is desired in the future, it can be added in a separate change.

## Risks & Mitigations
- Admin-only elements could accidentally remain visible due to logic errors — Mitigation: add explicit tests (and manual checks) for both logged-in and logged-out states, verifying that admin sections and buttons are conditionally rendered and that session expiration after one hour is enforced via the existing admin cookie TTL (and surfaced as 401/403 responses or `admin=false` from `/api/admin/status`).
- Responsive changes might break existing desktop layouts — Mitigation: use progressive, mobile-first CSS and test across typical desktop and mobile viewports; keep layout changes minimal and scoped.
- Confusion around login/logout state if visual cues are unclear — Mitigation: combine explicit text labels ("Admin Login", "Logout") with the dark red admin background, and document behavior in implementation notes.
- Activity section could become unclear if concurrent actions are allowed — Mitigation: serialize user-triggered actions in the UI, or clearly show only the latest initiated action, ensuring the message always refers to the current thing the user is waiting for.

## Open Questions
- Should admin session expiry (≤1 hour) be purely time-based since last login, or refreshed on each successful admin action? — Proposed answer: rely on the existing `pv2_admin` cookie TTL (`WEB_ADMIN_COOKIE_TTL_SECONDS`, default 3600s, clamped between 60 and 3600) as the single source of truth, treating it as “no more than one hour since last successful admin authentication” and surfacing expiry to the UI via `/api/admin/status` and 401/403 responses rather than client-side timers.
- Should the Activity section be hidden entirely when there is no current or recent action, or should it show an explicit "No active activity" placeholder? — Proposed answer: minimal placeholder ("No current activity") is acceptable but not required; implementers can choose based on UI clarity.


