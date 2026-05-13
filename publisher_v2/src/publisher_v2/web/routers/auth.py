import logging

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import RedirectResponse

from publisher_v2.utils.logging import log_json
from publisher_v2.web.auth import clear_admin_cookie, set_admin_cookie
from publisher_v2.web.dependencies import get_request_service
from publisher_v2.web.service import WebImageService

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("publisher_v2.web.auth0")

# OAuth instance is global but configured lazily
oauth = OAuth()


def configure_oauth(config):
    """
    Called by app startup to register Auth0.
    """
    if not config.auth0:
        return

    oauth.register(
        "auth0",
        client_id=config.auth0.client_id,
        client_secret=config.auth0.client_secret,
        client_kwargs={
            "scope": "openid email profile",
        },
        server_metadata_url=f"https://{config.auth0.domain}/.well-known/openid-configuration",
    )


def ensure_oauth_configured(service: WebImageService) -> bool:
    """
    Ensure OAuth is configured if the service has auth config.
    Returns True if configured, False otherwise.
    """
    if not oauth._registry.get("auth0") and service.config.auth0:
        configure_oauth(service.config)
    return bool(service.config.auth0)


def get_auth0_callback_url(request: Request) -> str | None:
    """
    Derive the Auth0 callback URL from the incoming request.

    With ``--proxy-headers`` enabled on uvicorn, ``request.url.scheme`` reflects
    the real client-facing scheme (via ``X-Forwarded-Proto``). The Host header
    on platforms like Heroku is set by the router and is trustworthy. Auth0
    itself also validates the callback URL against its configured allowlist,
    so a spoofed Host that doesn't match the Auth0 app config is rejected by
    the IdP before any code grant is issued.

    For localhost/127.0.0.1 the port is preserved for local dev convenience.
    For non-local hosts HTTPS is forced as a defence-in-depth measure.
    """
    hostname = request.url.hostname or ""
    if not hostname:
        return None

    port = request.url.port
    is_local = hostname in ("localhost", "127.0.0.1")

    if is_local:
        scheme = request.url.scheme or "http"
        netloc = hostname
        if port and ((scheme == "http" and port != 80) or (scheme == "https" and port != 443)):
            netloc = f"{hostname}:{port}"
        return f"{scheme}://{netloc}/auth/callback"

    return f"https://{hostname}/auth/callback"


@router.get("/login")
async def login(request: Request, service: WebImageService = Depends(get_request_service)):
    """
    Initiate the OIDC login flow.
    """
    if not ensure_oauth_configured(service):
        log_json(logger, logging.WARNING, "auth_login_disabled", reason="no_config")
        return RedirectResponse(url="/?auth_error=auth_not_configured", status_code=status.HTTP_303_SEE_OTHER)

    auth0_config = service.config.auth0
    if auth0_config is None:
        return RedirectResponse(url="/?auth_error=auth_not_configured", status_code=status.HTTP_303_SEE_OTHER)
    redirect_uri = get_auth0_callback_url(request) or auth0_config.callback_url
    if not redirect_uri:
        log_json(logger, logging.WARNING, "auth_login_disabled", reason="no_callback_url")
        return RedirectResponse(
            url="/?auth_error=auth_not_configured",
            status_code=status.HTTP_303_SEE_OTHER,
        )
    log_json(logger, logging.INFO, "auth_login_redirect", redirect_uri=redirect_uri)
    return await oauth.auth0.authorize_redirect(request, redirect_uri)


@router.get("/callback")
async def callback(request: Request, service: WebImageService = Depends(get_request_service)):
    """
    Handle the OIDC callback.
    """
    if not ensure_oauth_configured(service):
        return RedirectResponse(url="/?auth_error=auth_not_configured", status_code=status.HTTP_303_SEE_OTHER)

    auth0_config = service.config.auth0
    if auth0_config is None:
        return RedirectResponse(url="/?auth_error=auth_not_configured", status_code=status.HTTP_303_SEE_OTHER)

    try:
        # Check for error param from Auth0
        error = request.query_params.get("error")
        error_desc = request.query_params.get("error_description")
        if error:
            log_json(logger, logging.WARNING, "auth_callback_error", error=error, desc=error_desc)
            return RedirectResponse(url=f"/?auth_error={error}", status_code=status.HTTP_303_SEE_OTHER)

        redirect_uri = get_auth0_callback_url(request) or auth0_config.callback_url
        if not redirect_uri:
            log_json(logger, logging.WARNING, "auth_callback_no_redirect_uri")
            return RedirectResponse(
                url="/?auth_error=auth_not_configured",
                status_code=status.HTTP_303_SEE_OTHER,
            )

        # Authlib stores the redirect_uri used in authorize_redirect() in the session.
        # Passing redirect_uri again here can cause duplicate kwargs in some authlib versions.
        token = await oauth.auth0.authorize_access_token(request)
        user_info = token.get("userinfo")
        if not user_info:
            # Depending on authlib version/config, userinfo might be inside 'userinfo' key or merged.
            # If standard OIDC, id_token is parsed.
            user_info = await oauth.auth0.userinfo(token=token)

        email = user_info.get("email")
        email_verified = user_info.get("email_verified")

        if not email:
            log_json(logger, logging.WARNING, "auth_callback_no_email")
            return RedirectResponse(url="/?auth_error=no_email_provided", status_code=status.HTTP_303_SEE_OTHER)

        if email_verified is not True:
            # Refuse unverified emails — otherwise an attacker can sign up at
            # the IdP with a target email address and gain admin.
            log_json(logger, logging.WARNING, "auth_callback_unverified_email", email=email)
            request.session.clear()
            return RedirectResponse(url="/?auth_error=email_unverified", status_code=status.HTTP_303_SEE_OTHER)

        # Check allowlist (case-insensitive)
        email_lower = email.lower()
        allowed_emails = [e.lower() for e in auth0_config.admin_emails_list]

        if email_lower not in allowed_emails:
            log_json(logger, logging.WARNING, "auth_access_denied", email=email)
            # Clear any session state just in case
            request.session.clear()
            return RedirectResponse(url="/?auth_error=access_denied", status_code=status.HTTP_303_SEE_OTHER)

        # Success
        log_json(logger, logging.INFO, "auth_login_success", email=email)
        response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        set_admin_cookie(response)
        request.session.clear()  # OIDC state no longer needed
        return response

    except Exception as exc:
        log_json(logger, logging.ERROR, "auth_callback_exception", error=str(exc))
        return RedirectResponse(url="/?auth_error=callback_failed", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/logout")
async def logout(request: Request):
    """
    Clear the local session and cookie.
    """
    log_json(logger, logging.INFO, "auth_logout")
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    clear_admin_cookie(response)
    request.session.clear()
    return response
