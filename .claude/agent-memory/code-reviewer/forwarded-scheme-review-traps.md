---
name: forwarded-scheme-review-traps
description: "#129 X-Forwarded-Proto review traps: multi-value refusal vs Cloudflare double-proxy, Heroku append/overwrite is unsourced, lifespan tests run real init_db/dispose"
metadata:
  type: project
---

Reviewing anything that reads `X-Forwarded-Proto` / `WEB_TRUST_FORWARDED_FOR` in
`publisher_v2/web/rate_limit.py` (`request_scheme`, `trust_forwarded_headers`):

- Taking the FIRST XFP value is unsafe when any proxy appends (client forgery ends up leftmost).
  Starlette `headers.get` returns the first of duplicate lines, so the comma form and the
  duplicate-header form are the same attack — a test must cover both.
- Refusing multi-valued XFP is the safe rule (uvicorn's `ProxyHeadersMiddleware` does the same:
  it strips the whole header and only applies exact `http`/`https`/`ws`/`wss`). But it breaks the
  Cloudflare-in-front-of-Heroku shape IF Heroku appends (`https,https`) — which is the same
  unsourced append-vs-overwrite claim that keeps appearing in docstrings. Single-proxy Heroku is
  safe either way because browsers do not send XFP. "Honour when all values are identical" is the
  refinement that keeps both properties.
- **Why:** #129 is the deploy blocker (CSRF 403 on every browser POST); #128 failure mode (d) is
  "a deployment-facing change made without tracing what the production proxy does".
- **How to apply:** any change here must be checked against BOTH the single-proxy and double-proxy
  shapes, and any Heroku router behaviour claim must be sourced or marked as needing a staging check.

Tests that run the REAL `publisher_v2.web.app.lifespan` (`async with lifespan(app)`) execute
`setup_logging` (clears root handlers — caplog is useless in that test, use capsys), `init_db`, and
the whole shutdown path (`dispose_engine`, `aclose_shared_client`, tenant factory shutdown). Safe
today only because neither CI nor the local suite sets `DATABASE_URL` and `_tenant_service_factory()`
builds a fresh uncached factory. Check env-dependence before trusting a green run.

`capsys`-based log assertions in `publisher_v2/tests/web/` are order-dependent: log output only
reaches stderr once something has run `setup_logging()` (the real lifespan does), so a `capsys`
assertion passes after a lifespan test and fails when it runs first. Caught #129's
`test_csrf_rejection_hints_at_disagreeing_forwarded_proto` failing on ~1 run in 5 under the
pre-commit hook (pytest-randomly picks a fresh seed each run, so fixed seeds 1/2/3 can all be
green while the hook is red). Use `caplog` for anything that does NOT itself call `setup_logging`.
