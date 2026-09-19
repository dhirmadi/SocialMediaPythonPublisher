"""Security response-header middleware.

Adds defense-in-depth headers to every response:

- ``Content-Security-Policy``: blocks framing, restricts default sources to
  same-origin. #91 (SEC-8): ``script-src`` uses a per-request nonce instead of
  ``'unsafe-inline'`` — the template's single inline block carries the nonce.
  ``connect-src`` allows https: because the Full Size control fetches the
  per-tenant presigned storage URL (Dropbox/R2 origins vary per tenant).
- ``Strict-Transport-Security``: sent when WEB_SECURE_COOKIES is enabled
  (i.e. production-like TLS deployments).
- ``X-Frame-Options: DENY``: legacy clickjacking guard for browsers that ignore
  CSP frame-ancestors.
- ``X-Content-Type-Options: nosniff``: prevents MIME sniffing on responses.
- ``Referrer-Policy: same-origin``: don't leak full URLs to third parties.
"""

from __future__ import annotations

import os
import secrets

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

_CSP_TEMPLATE = (
    "default-src 'self'; "
    "img-src 'self' data: blob: https:; "
    "script-src 'self' 'nonce-{nonce}'; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self' https:; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self';"
)

_HSTS_VALUE = "max-age=31536000; includeSubDomains"


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, *, csp_template: str = _CSP_TEMPLATE) -> None:
        super().__init__(app)
        self._csp_template = csp_template

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        # Per-request nonce, exposed to the template renderer via request.state.
        nonce = secrets.token_urlsafe(16)
        request.state.csp_nonce = nonce
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", self._csp_template.format(nonce=nonce))
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if (os.environ.get("WEB_SECURE_COOKIES") or "true").lower() in ("1", "true", "yes", "on"):
            response.headers.setdefault("Strict-Transport-Security", _HSTS_VALUE)
        return response
