import base64
import hmac
import logging
import os
import secrets

from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

logger = logging.getLogger("publisher_v2.web.auth")


def _get_env(name: str) -> str | None:
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


def _allow_unauthenticated() -> bool:
    """Explicit dev opt-in to bypass auth when no backend is configured."""
    return (_get_env("WEB_ALLOW_UNAUTHENTICATED") or "").lower() in ("1", "true", "yes", "on")


async def require_auth(request: Request) -> None:
    """
    Enforce simple auth for mutating endpoints.

    Supports either:
      - Bearer token via WEB_AUTH_TOKEN, or
      - HTTP Basic auth via WEB_AUTH_USER / WEB_AUTH_PASS, or
      - An active admin cookie (signed) — for same-origin browser admins
        who already authenticated via /api/admin/login or /auth/callback.

    Fail-closed: when no auth backend is configured AND admin mode is not
    configured AND WEB_ALLOW_UNAUTHENTICATED is not set, refuses the request.
    """
    if is_auth_enabled():
        # Header-based auth takes precedence for machine clients.
        auth_header = (request.headers.get("authorization") or "").strip()
        if auth_header:
            if _verify_bearer(auth_header) or _verify_basic(auth_header):
                return
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
        # No header — fall through to admin cookie check below.

    # Browser admins authenticated via cookie are also allowed for mutating routes.
    if is_admin_configured() and is_admin_request(request):
        return

    if is_auth_enabled():
        # Backend exists but caller provided no valid credentials.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    # No backend configured: require explicit opt-in.
    if _allow_unauthenticated():
        return
    if is_admin_configured():
        # Admin cookie required and was not present.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="No auth backend configured. Set WEB_AUTH_TOKEN, WEB_AUTH_USER/WEB_AUTH_PASS, web_admin_pw, or AUTH0_DOMAIN/AUTH0_CLIENT_ID.",
    )


def _verify_bearer(auth_header: str) -> bool:
    token_cfg = _get_env("WEB_AUTH_TOKEN")
    if not token_cfg or not auth_header.lower().startswith("bearer "):
        return False
    provided = auth_header[7:].strip()
    if not provided:
        return False
    # #87 (SEC-9): compare bytes — compare_digest raises TypeError on
    # non-ASCII str input, which surfaced as a 500 instead of a 401.
    return hmac.compare_digest(provided.encode("utf-8"), token_cfg.encode("utf-8"))


def _verify_basic(auth_header: str) -> bool:
    user_cfg = _get_env("WEB_AUTH_USER")
    pass_cfg = _get_env("WEB_AUTH_PASS")
    if not (user_cfg and pass_cfg) or not auth_header.lower().startswith("basic "):
        return False
    b64 = auth_header[6:].strip()
    try:
        decoded = base64.b64decode(b64).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    if ":" not in decoded:
        return False
    user, pwd = decoded.split(":", 1)
    # Constant-time compare on both components (bytes: see SEC-9 note above).
    return hmac.compare_digest(user.encode("utf-8"), user_cfg.encode("utf-8")) and hmac.compare_digest(
        pwd.encode("utf-8"), pass_cfg.encode("utf-8")
    )


# --- Admin-mode helpers (UI-level guard on top of HTTP auth) ---

ADMIN_COOKIE_NAME = "pv2_admin"
_ADMIN_COOKIE_SALT = "publisher_v2.admin_cookie.v1"


def get_admin_password() -> str | None:
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
    if get_admin_password() is not None:
        return True
    return bool(_get_env("AUTH0_DOMAIN") and _get_env("AUTH0_CLIENT_ID"))


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
    except (TypeError, ValueError):
        return False


def _admin_cookie_ttl_seconds() -> int:
    """Admin cookie TTL clamped to [60s, 3600s] per .claude/rules/web-security.md."""
    raw = os.environ.get("WEB_ADMIN_COOKIE_TTL_SECONDS")
    try:
        value = int(raw) if raw is not None else 3600
    except ValueError:
        value = 3600
    return max(60, min(value, 3600))


def _cookie_secret() -> str:
    """
    Secret used to sign the admin cookie. Reuses the session secret so operators
    only need to configure one. Falls back to a dev secret when WEB_DEBUG=1.
    """
    secret = os.environ.get("WEB_SESSION_SECRET") or os.environ.get("SECRET_KEY")
    if secret:
        return secret
    if (os.environ.get("WEB_DEBUG") or "").lower() in ("1", "true", "yes", "on"):
        return "dev_secret_do_not_use_in_prod"
    raise RuntimeError(
        "Missing WEB_SESSION_SECRET / SECRET_KEY required to sign admin cookies. "
        "Set one in the environment, or enable WEB_DEBUG=1 for local development."
    )


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_cookie_secret(), salt=_ADMIN_COOKIE_SALT)


def _normalize_host(value: str | None) -> str | None:
    """Normalize a Host header / runtime host for binding comparisons."""
    if not value:
        return None
    return value.strip().lower() or None


def mint_admin_cookie_value(
    *,
    tenant: str | None = None,
    host: str | None = None,
    mode: str = "password",
    email: str | None = None,
) -> str:
    """
    Mint a signed admin-cookie payload bound to a tenant and host (SEC-1).

    Payload: {"sid", "tenant", "host", "mode", "email"?}. Signature and
    timestamp are embedded by URLSafeTimedSerializer. Exposed so tests can
    construct valid cookies.
    """
    payload: dict[str, str | None] = {
        "sid": secrets.token_urlsafe(16),
        "tenant": tenant,
        "host": _normalize_host(host),
        "mode": mode,
    }
    if email:
        payload["email"] = email
    return _serializer().dumps(payload)


def _load_admin_cookie(token: str | None) -> dict | None:
    """Verify signature and age, then require the bound-payload shape.

    Legacy cookies (pre tenant/host binding) lack the required claims and are
    rejected. Returns the payload dict, or None when the cookie is invalid.
    """
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=_admin_cookie_ttl_seconds())
    except SignatureExpired:
        return None
    except BadSignature:
        return None
    except Exception:  # pragma: no cover — defensive
        logger.warning("admin_cookie_decode_unexpected", exc_info=True)
        return None
    if not isinstance(data, dict):
        return None
    if not all(key in data for key in ("sid", "tenant", "host", "mode")):
        return None
    return data


def request_binding(request: Request) -> tuple[str | None, str | None]:
    """
    Resolve the (tenant, host) pair the admin cookie must be bound to.

    Orchestrator mode: tenant middleware sets request.state.tenant/.host.
    Standalone mode: no tenant; the normalized Host header is the binding.
    """
    tenant = getattr(request.state, "tenant", None)
    host = getattr(request.state, "host", None) or request.headers.get("host")
    return tenant, _normalize_host(host)


def set_admin_cookie(
    response: Response,
    expires_in_seconds: int | None = None,
    *,
    tenant: str | None = None,
    host: str | None = None,
    mode: str = "password",
    email: str | None = None,
) -> None:
    """
    Set the signed admin-mode cookie on the response, bound to tenant/host.
    """
    ttl = expires_in_seconds if expires_in_seconds is not None else _admin_cookie_ttl_seconds()
    secure = (_get_env("WEB_SECURE_COOKIES") or "true").lower() in ("1", "true", "yes")
    response.set_cookie(
        key=ADMIN_COOKIE_NAME,
        value=mint_admin_cookie_value(tenant=tenant, host=host, mode=mode, email=email),
        max_age=ttl,
        httponly=True,
        secure=secure,
        samesite="strict",
        path="/",
    )


def clear_admin_cookie(response: Response) -> None:
    response.delete_cookie(key=ADMIN_COOKIE_NAME, path="/")


def is_admin_request(request: Request) -> bool:
    """
    Determine whether the incoming request is in admin mode by verifying the
    signed cookie AND its tenant/host binding (SEC-1). Returns False on
    missing, tampered, expired, legacy, or cross-tenant cookies.
    """
    payload = _load_admin_cookie(request.cookies.get(ADMIN_COOKIE_NAME))
    if payload is None:
        return False
    tenant, host = request_binding(request)
    if payload.get("tenant") != tenant:
        return False
    return payload.get("host") == host


def _tenant_admin_available(request: Request) -> bool | None:
    """
    Per-tenant admin auth policy from the orchestrator runtime config.

    Returns None in standalone mode (no request.state.config); otherwise True
    when the resolved tenant allows some admin login (Auth0 enabled via a
    non-None auth0 config, or a password login configured on this instance).
    """
    cfg = getattr(request.state, "config", None)
    if cfg is None:
        return None
    auth0_enabled = getattr(cfg, "auth0", None) is not None
    return auth0_enabled or get_admin_password() is not None


def require_admin(request: Request) -> None:
    """
    Enforce admin mode for web-triggered mutating actions.

    Orchestrator mode: the resolved tenant's runtime config decides whether
    any admin login exists for the tenant; a disabled tenant gets 403 even
    with a validly signed cookie. Standalone mode: env-based configuration.
    """
    tenant_policy = _tenant_admin_available(request)
    if tenant_policy is False:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin mode disabled for this tenant",
        )
    if tenant_policy is None and not is_admin_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin mode not configured",
        )
    if not is_admin_request(request):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
