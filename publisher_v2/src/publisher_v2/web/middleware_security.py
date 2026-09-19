"""Security response-header middleware.

Adds defense-in-depth headers to every response:

- ``Content-Security-Policy``: blocks framing, restricts default sources to
  same-origin. #91 (SEC-8): ``script-src`` uses a per-request nonce instead of
  ``'unsafe-inline'`` — the template's single inline block carries the nonce.
  ``img-src``/``connect-src`` allow the tenant's own storage origin (#144), so
  the Full Size control can fetch the presigned URL without opening the page up
  to every https origin.
- ``Strict-Transport-Security``: sent when WEB_SECURE_COOKIES is enabled
  (i.e. production-like TLS deployments).
- ``X-Frame-Options: DENY``: legacy clickjacking guard for browsers that ignore
  CSP frame-ancestors.
- ``X-Content-Type-Options: nosniff``: prevents MIME sniffing on responses.
- ``Referrer-Policy: same-origin``: don't leak full URLs to third parties.
"""

from __future__ import annotations

import os
import re
import secrets
from typing import Any
from urllib.parse import urlparse

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp

# #144: {storage} is the configured storage origin the Full Size control fetches
# from. It used to be a blanket ``https:``, which let any script on the page ship
# whatever it could read to any https origin.
_CSP_TEMPLATE = (
    "default-src 'self'; "
    "img-src 'self' data: blob:{storage}; "
    "script-src 'self' 'nonce-{nonce}'; "
    "style-src 'self' 'unsafe-inline'; "
    "connect-src 'self'{storage}; "
    "frame-ancestors 'none'; "
    "base-uri 'self'; "
    "form-action 'self';"
)

# Dropbox hands out presigned links on rotating uc*.dropboxusercontent.com hosts.
_DROPBOX_CONTENT_ORIGINS = ("https://*.dropboxusercontent.com",)

# A CSP source must be a bare host[:port]. endpoint_url is operator- or, in
# orchestrated mode, tenant-supplied: an unvalidated netloc containing a space
# or a ";" would smuggle an extra source — or a whole extra directive, which
# browsers honour in FIRST-occurrence order, overriding the nonce script-src.
_SAFE_NETLOC_RE = re.compile(r"[A-Za-z0-9.\-]+(?::\d{1,5})?")


def storage_origins_for_config(config: Any) -> list[str]:
    """Origins a page backed by this config may fetch image bytes from.

    Managed storage: the configured endpoint origin. Dropbox: its content hosts.
    Anything unrecognised or unsafe: nothing extra, leaving the directives at
    ``'self'``.
    """
    if config is None:
        return []
    managed = getattr(config, "managed", None)
    endpoint = getattr(managed, "endpoint_url", None)
    if endpoint:
        parsed = urlparse(endpoint)
        if parsed.scheme in ("http", "https") and _SAFE_NETLOC_RE.fullmatch(parsed.netloc or ""):
            return [f"{parsed.scheme}://{parsed.netloc}"]
        return []
    if getattr(config, "dropbox", None) is not None:
        return list(_DROPBOX_CONTENT_ORIGINS)
    return []


def _storage_origins(request: Request) -> list[str]:
    """This request's storage origins: the tenant's config, else the startup snapshot."""
    config = getattr(request.state, "config", None)
    if config is None:
        service = getattr(request.state, "web_service", None)
        config = getattr(service, "config", None)
    if config is not None:
        return storage_origins_for_config(config)
    # Standalone: resolved once at startup, so a cold process still serves the
    # right policy on its very first page render.
    try:
        return list(request.app.state.csp_storage_origins or [])
    except (AttributeError, KeyError):
        return []


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
        # Resolved after the downstream call so tenant middleware has attached
        # this request's config.
        origins = _storage_origins(request)
        storage = "" if not origins else " " + " ".join(origins)
        response.headers.setdefault("Content-Security-Policy", self._csp_template.format(nonce=nonce, storage=storage))
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        if (os.environ.get("WEB_SECURE_COOKIES") or "true").lower() in ("1", "true", "yes", "on"):
            response.headers.setdefault("Strict-Transport-Security", _HSTS_VALUE)
        return response
