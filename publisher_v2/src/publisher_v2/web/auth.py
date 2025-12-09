from __future__ import annotations

import base64
import hmac
import os
from typing import Optional

from fastapi import Request, HTTPException, Response, status


def _get_env(name: str) -> Optional[str]:
    value = os.environ.get(name)
    if value is None or not str(value).strip():
        return None
    return value.strip()


def is_auth_enabled() -> bool:
    """
    Determine whether web auth is enabled based on environment variables.

    MVP rule:
      - If any of WEB_AUTH_TOKEN or (WEB_AUTH_USER and WEB_AUTH_PASS) is set,
        auth is considered enabled for mutating endpoints.
    """
    token = _get_env("WEB_AUTH_TOKEN")
    user = _get_env("WEB_AUTH_USER")
    pwd = _get_env("WEB_AUTH_PASS")
    return bool(token or (user and pwd))


async def require_auth(request: Request) -> None:
    """
    Enforce simple auth for mutating endpoints.

    Supports either:
      - Bearer token via WEB_AUTH_TOKEN, or
      - HTTP Basic auth via WEB_AUTH_USER / WEB_AUTH_PASS.
    """
    if not is_auth_enabled():
        # Auth disabled → allow
        return

    auth_header = request.headers.get("authorization") or ""
    auth_header = auth_header.strip()
    if not auth_header:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    # Bearer token
    token_cfg = _get_env("WEB_AUTH_TOKEN")
    if token_cfg and auth_header.lower().startswith("bearer "):
        provided = auth_header[7:].strip()
        if provided and provided == token_cfg:
            return
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    # Basic auth
    user_cfg = _get_env("WEB_AUTH_USER")
    pass_cfg = _get_env("WEB_AUTH_PASS")
    if user_cfg and pass_cfg and auth_header.lower().startswith("basic "):
        b64 = auth_header[6:].strip()
        try:
            decoded = base64.b64decode(b64).decode("utf-8")
        except Exception:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        if ":" not in decoded:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        user, pwd = decoded.split(":", 1)
        if user == user_cfg and pwd == pass_cfg:
            return

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


# --- Admin-mode helpers (UI-level guard on top of HTTP auth) ---

ADMIN_COOKIE_NAME = "pv2_admin"


def get_admin_password() -> Optional[str]:
    """
    Read the admin password from environment (web_admin_pw).

    Returns None when not configured or empty, which disables admin mode.
    """
    # Intentionally lower-case to match .env naming in the change request.
    return _get_env("web_admin_pw")


def is_admin_configured() -> bool:
    """
    Check if admin mode is available via either legacy password or Auth0.
    """
    # Legacy password check
    if get_admin_password() is not None:
        return True
    
    # Auth0 check (MVP: check for domain env var, mirroring config loader)
    if _get_env("AUTH0_DOMAIN") and _get_env("AUTH0_CLIENT_ID"):
        return True
        
    return False


def get_auth_mode() -> str:
    """
    Determine the active authentication mode.
    Returns: 'auth0', 'password', or 'none'.
    """
    if _get_env("AUTH0_DOMAIN") and _get_env("AUTH0_CLIENT_ID"):
        return "auth0"
    if get_admin_password() is not None:
        return "password"
    return "none"


def verify_admin_password(candidate: str, actual: str) -> bool:
    """
    Constant-time comparison helper for admin passwords.
    """
    if not candidate or not actual:
        return False
    try:
        return hmac.compare_digest(candidate, actual)
    except Exception:
        return False


def _admin_cookie_ttl_seconds() -> int:
    # Default to 1 hour; allow override while keeping it bounded.
    raw = os.environ.get("WEB_ADMIN_COOKIE_TTL_SECONDS")
    try:
        value = int(raw) if raw is not None else 3600
    except ValueError:
        value = 3600
    # Clamp to a sensible minimum/maximum.
    return max(60, min(value, 3600))


def set_admin_cookie(response: Response, expires_in_seconds: Optional[int] = None) -> None:
    """
    Set the admin-mode cookie on the response.
    """
    ttl = expires_in_seconds if expires_in_seconds is not None else _admin_cookie_ttl_seconds()
    # Default to non-secure for local/testing; production can enable via WEB_SECURE_COOKIES.
    secure = (_get_env("WEB_SECURE_COOKIES") or "true").lower() in ("1", "true", "yes")
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value="1",
        max_age=ttl,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_admin_cookie(response: Response) -> None:
    response.delete_cookie(key=ADMIN_COOKIE_NAME, path="/")


def is_admin_request(request: Request) -> bool:
    """
    Determine whether the incoming request is in admin mode based on cookie.
    """
    return bool(request.cookies.get(ADMIN_COOKIE_NAME))


def require_admin(request: Request) -> None:
    """
    Enforce admin mode for web-triggered mutating actions.

    If no admin auth (password or Auth0) is configured, admin mode is considered unavailable.
    """
    if not is_admin_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin mode not configured",
        )
    if not is_admin_request(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )

