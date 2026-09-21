---
name: dropbox-retry-review-traps
description: "#132 Dropbox retry review traps: tenacity waits are 1s+2s not the 8s cap, bounds are per decorated call not per request, Heroku 30s router vs the 30s Retry-After cap"
metadata:
  type: project
---

Reviewing anything that documents `services/storage.py` retry behaviour: compute the waits, don't quote the bound.

**Why:** `_dropbox_retry` is `stop_after_attempt(3)` + `wait_exponential(multiplier=1, min=1, max=8)`.
With 3 attempts tenacity only ever computes waits for attempt_number 1 and 2, i.e. **1.0s then 2.0s
(3s total)** — the `max=8` ceiling is unreachable. Prose that says "up to ~16s of retries" (2x8s) or
"≤8s per wait" is quoting an unreachable ceiling. Verify with
`PYTHONPATH=publisher_v2/src uv run python` calling `_dropbox_wait` with a fake retry_state, or by
monkeypatching `asyncio.sleep` around a real `DropboxStorage` call.

**How to apply:**
- Waits are per **decorated method**, not per HTTP request. One `/api/images/{f}/analyze` makes
  several decorated calls (`get_temporary_link`, `download_sidecar_if_exists`, `list_images`), each
  with its own 3 attempts, so a per-request worst case is a multiple of the per-call one.
- Attempt time (30s SDK timeout each) is not counted in the wait bound; a "fails after ≤60s" claim
  is waits-only and should say so.
- The app runs on Heroku (`Procfile`, uvicorn) whose router cuts responses at 30s, so the
  "keep the admin request responsive" justification for `MAX_RATE_LIMIT_BACKOFF_SECONDS = 30` only
  half-holds: one capped wait already spends the whole router budget.
- SDK 12.0.2 `dropbox_client.py request_json_string_with_retry`: `max_retries_on_error=0` and
  `max_retries_on_rate_limit=0` do disable both loops (`0 >= 1` is False), but the
  expired-access-token branch still re-sends once after `refresh_access_token()` — that is a real
  in-SDK resend and should be named, not called "no internal retry".
