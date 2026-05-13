"""Helpers for sanitizing publisher error strings before they leak outwards.

Exception messages from SDKs frequently contain secrets:
- Telegram URLs embed the bot token: ``https://api.telegram.org/bot<TOKEN>/sendPhoto``
- SMTP server responses can echo the username/AUTH line.
- instagrapi raises exceptions that include cookies/CSRF tokens.

``sanitize_publisher_error`` strips well-known patterns and trims length so the
remaining text is safe to put into ``PublishResult.error`` (which is logged and
returned to API clients).
"""

from __future__ import annotations

import re

_TELEGRAM_TOKEN_RE = re.compile(r"\bbot[0-9]{6,}:[A-Za-z0-9_-]{20,}", re.IGNORECASE)
_BEARER_RE = re.compile(r"(bearer)\s+[A-Za-z0-9._\-]+", re.IGNORECASE)
_BASIC_RE = re.compile(r"(basic)\s+[A-Za-z0-9+/=]+", re.IGNORECASE)
_AUTH_KV_RE = re.compile(r'(authorization|password|secret|token|api[_-]?key)\s*[:=]\s*["\']?\S+', re.IGNORECASE)
# Strip embedded URLs entirely — they often carry credentials in the path/query.
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)

_MAX_LEN = 200


def sanitize_publisher_error(exc: BaseException) -> str:
    """Return a redacted, length-capped representation of ``exc``."""
    raw = f"{type(exc).__name__}: {exc}"
    redacted = _TELEGRAM_TOKEN_RE.sub("bot<redacted>", raw)
    redacted = _BEARER_RE.sub(r"\1 <redacted>", redacted)
    redacted = _BASIC_RE.sub(r"\1 <redacted>", redacted)
    redacted = _AUTH_KV_RE.sub(r"\1=<redacted>", redacted)
    redacted = _URL_RE.sub("<url>", redacted)
    if len(redacted) > _MAX_LEN:
        redacted = redacted[: _MAX_LEN - 1] + "…"
    return redacted
