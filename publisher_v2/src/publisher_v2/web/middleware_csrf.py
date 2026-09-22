"""CSRF protection middleware for the FastAPI admin UI.

Strategy: for any state-changing request (POST/PUT/PATCH/DELETE) under /api/*,
require ONE of:

  (a) An ``Authorization`` header that *verifies* — machine clients with valid
      Bearer/Basic creds. These are unaffected by CSRF because the attacker
      cannot forge valid credentials from a victim browser. An unverified
      header grants no bypass (PUB-048 AC3).
  (b) Both: an ``X-Requested-With: XMLHttpRequest`` header AND a same-origin
      ``Origin`` (or ``Referer`` fallback). Browsers prevent cross-origin pages
      from setting custom request headers without a CORS preflight, so this
      pair-check blocks classic cross-site form submissions.

Routes that legitimately need to accept cross-site GETs (Auth0 redirect callback)
are unaffected because the middleware only runs on state-changing methods.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

from publisher_v2.utils.logging import log_json
from publisher_v2.web.auth import _verify_basic, _verify_bearer
from publisher_v2.web.rate_limit import forwarded_proto_values, request_scheme, trust_forwarded_headers

logger = logging.getLogger("publisher_v2.web.csrf")

_STATE_CHANGING = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Endpoints that must remain reachable without prior cookie/header context.
# Auth bootstrap routes only — every other route is protected.
_CSRF_EXEMPT_PATHS: frozenset[str] = frozenset(
    {
        "/auth/callback",  # OIDC redirect target (state-changing in OIDC sense, but GET)
    }
)


def _same_origin(request: Request, origin: str | None) -> bool:
    if not origin:
        return False
    try:
        parsed = urlparse(origin)
    except ValueError:
        return False
    host = request.headers.get("host", "")
    if not host:
        return False
    expected = f"{parsed.scheme}://{parsed.netloc}".lower()
    actual_scheme = request_scheme(request)
    actual = f"{actual_scheme}://{host}".lower()
    return expected == actual


class CSRFMiddleware(BaseHTTPMiddleware):
    """Block cross-site state-changing requests that lack a CSRF signal."""

    def __init__(self, app: ASGIApp, *, api_prefix: str = "/api") -> None:
        """Wrap ``app``, guarding state-changing requests under ``api_prefix`` only."""
        super().__init__(app)
        self._api_prefix = api_prefix

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        """Pass the request through, or answer 403 when the CSRF signal is missing.

        Skipped entirely for non-state-changing methods, paths outside the API prefix,
        exempt auth-bootstrap paths, requests carrying a *verified* ``Authorization`` header, and
        cookieless requests (no victim session to ride — auth dependencies reject those).
        """
        if request.method not in _STATE_CHANGING:
            return await call_next(request)
        path = request.url.path
        if not path.startswith(self._api_prefix):
            return await call_next(request)
        if path in _CSRF_EXEMPT_PATHS:
            return await call_next(request)

        # Machine clients with a *verified* Authorization header bypass CSRF —
        # credentials in the header cannot be forged from a victim browser.
        # PUB-048 (AC3): mere presence is not enough. An attacker page can make
        # the browser send an arbitrary `Authorization: Bearer nope` alongside
        # the victim's cookie, so an unverified header used to be a free CSRF
        # bypass. An invalid header now falls through to the X-Requested-With
        # branch below and is rejected there.
        auth_header = (request.headers.get("authorization") or "").strip()
        if auth_header and (_verify_bearer(auth_header) or _verify_basic(auth_header)):
            return await call_next(request)

        # No cookies on the request means there is no victim session to ride —
        # whatever else this request is, it isn't a classical CSRF. Let it
        # through and let the route's auth dependency decide whether to allow
        # or 401 it. (A direct curl with no cookies and no auth is rejected
        # by require_auth, not by the CSRF layer.)
        if not request.cookies:
            return await call_next(request)

        # Browser clients: require X-Requested-With. Cross-origin pages
        # cannot set this custom header without a CORS preflight (which we
        # don't grant for state-changing routes), so its presence is itself
        # a same-origin signal. Origin/Referer are validated as a second
        # layer when they're present — but their absence is not fatal
        # (some browsers / test clients omit them).
        xrw = request.headers.get("x-requested-with", "").lower()
        if xrw != "xmlhttprequest":
            return _reject(request, "missing X-Requested-With header")

        origin = request.headers.get("origin")
        if origin and not _same_origin(request, origin):
            return _reject(request, "cross-origin Origin")

        referer = request.headers.get("referer")
        if not origin and referer and not _same_origin(request, referer):
            return _reject(request, "cross-origin Referer")

        return await call_next(request)


def _reject(request: Request, reason: str) -> JSONResponse:
    # #129: behind a proxy the commonest cause of a cross-origin rejection is not
    # a cross-origin request at all — it is the scheme, because the forwarded
    # headers are untrusted or disagree. Say so in the log rather than making the
    # next operator rediscover it. Both the Origin and the Referer branch have
    # the identical cause, so both get the hint.
    hint = None
    if reason in ("cross-origin Origin", "cross-origin Referer"):
        if not trust_forwarded_headers(request):
            hint = "set WEB_TRUST_FORWARDED_FOR=true if this app sits behind a TLS-terminating proxy"
        elif len(set(forwarded_proto_values(request))) > 1:
            # The least diagnosable case: the flag IS set, so the operator has
            # already done the documented fix, and the scheme still fell back.
            hint = (
                "X-Forwarded-Proto carries disagreeing values, so it is not trusted; "
                "check for a proxy in front that terminates TLS and forwards plain http "
                "(e.g. Cloudflare SSL mode 'Flexible')"
            )
    log_json(
        logger,
        logging.WARNING,
        "csrf_block",
        path=request.url.path,
        method=request.method,
        reason=reason,
        remote=request.client.host if request.client else None,
        hint=hint,
    )
    return JSONResponse(
        status_code=403,
        content={"detail": "CSRF check failed"},
    )
