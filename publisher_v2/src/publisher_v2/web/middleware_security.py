"""Security response-header middleware.

Adds defense-in-depth headers to every response:

- ``Content-Security-Policy``: blocks framing, restricts default sources to
  same-origin. ``script-src 'self' 'unsafe-inline'`` is kept because the admin
  UI uses inline JS by design — switching to nonces is out of scope here.
- ``X-Frame-Options: DENY``: legacy clickjacking guard for browsers that ignore
  CSP frame-ancestors.
- ``X-Content-Type-Options: nosniff``: prevents MIME sniffing on responses.
- ``Referrer-Policy: same-origin``: don't leak full URLs to third parties.
"""

from __future__ import annotations

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

_DEFAULT_CSP = (
    "default-src 'self'; "
    "img-src 'self' data: blob: https:; "
    "script-src 'self' 'unsafe-inline'; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self';"
)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, csp: str = _DEFAULT_CSP) -> None:
        super().__init__(app)
        self._csp = csp

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", self._csp)
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        return response
