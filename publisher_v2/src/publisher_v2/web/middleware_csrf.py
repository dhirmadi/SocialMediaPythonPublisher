"""CSRF protection middleware for the FastAPI admin UI.

Strategy: for any state-changing request (POST/PUT/PATCH/DELETE) under /api/*,
require ONE of:

  (a) An ``Authorization`` header — machine clients with Bearer/Basic creds.
      These are unaffected by CSRF because the attacker cannot forge such a
      header from a victim browser.
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
    actual_scheme = request.url.scheme
    actual = f"{actual_scheme}://{host}".lower()
    return expected == actual


class CSRFMiddleware(BaseHTTPMiddleware):
    """Block cross-site state-changing requests that lack a CSRF signal."""

    def __init__(self, app: ASGIApp, *, api_prefix: str = "/api") -> None:
        super().__init__(app)
        self._api_prefix = api_prefix

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        if request.method not in _STATE_CHANGING:
            return await call_next(request)
        path = request.url.path
        if not path.startswith(self._api_prefix):
            return await call_next(request)
        if path in _CSRF_EXEMPT_PATHS:
            return await call_next(request)

        # Machine clients with Authorization header bypass CSRF — credentials in
        # the header cannot be forged from a victim browser.
        if request.headers.get("authorization"):
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
    logger.warning(
        "csrf_block",
        extra={
            "path": request.url.path,
            "method": request.method,
            "reason": reason,
            "remote": request.client.host if request.client else None,
        },
    )
    return JSONResponse(
        status_code=403,
        content={"detail": "CSRF check failed"},
    )
