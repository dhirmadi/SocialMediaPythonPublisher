---
name: web-template-test-traps
description: Review trap for index.html fixes — middleware/API tests pass with and without a JS fix; only template-string asserts catch it. Verify by checking out main's template and rerunning.
metadata:
  type: project
---

For bug fixes in `publisher_v2/src/publisher_v2/web/templates/index.html` (vanilla JS, no build), TestClient tests against the API/middleware cannot exercise the JS. Tests that "prove" the fix pass identically before and after; only a test that asserts the literal source line in `GET /` output actually regresses.

**Why:** Verified 2026-09-19 on fix/library-upload-csrf-header — 2 of 3 new TestUploadCsrf tests passed against main's template; only the HTML-string assert failed.

**How to apply:** For any index.html diff, run `git checkout main -- <template>` and rerun the new tests; require at least one to fail. Restore with `git checkout HEAD -- <template>` afterward. Also note: `window.fetch` is wrapped at ~line 905 to add `X-Requested-With`; raw `XMLHttpRequest` / `sendBeacon` / form submits bypass it — grep for those when reviewing CSRF-adjacent changes.

**Visibility trap (#137, 2026-09-19):** a template-string assert proves a message is in the page source, not that it is visible. `#details` sits inside `#panel-activity`, which `updateAdminUI()` hides for non-admins (`.hidden` is `display:none !important`), and `setDetails()` overwrites `#details` on every image load. Messages meant for logged-out users must go somewhere visible (e.g. the image placeholder or a non-admin-only element). Check the parent container's `.hidden` state before accepting a "UI says so" test.
