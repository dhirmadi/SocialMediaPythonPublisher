from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Optional, Any

from fastapi import FastAPI, Depends, HTTPException, Request, status, Query
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from publisher_v2.config.static_loader import get_static_config
from publisher_v2.utils.logging import setup_logging, log_json, now_monotonic, elapsed_ms
from publisher_v2.web.auth import (
    require_auth,
    require_admin,
    is_admin_configured,
    get_admin_password,
    verify_admin_password,
    set_admin_cookie,
    clear_admin_cookie,
    is_admin_request,
    get_auth_mode,
)
from publisher_v2.web.routers import auth as auth_router
from publisher_v2.web.models import (
    ImageResponse,
    ImageListResponse,
    AnalysisResponse,
    PublishResponse,
    PublishRequest,
    ErrorResponse,
    AdminLoginRequest,
    AdminStatusResponse,
    CurationResponse,
)
from publisher_v2.web.service import WebImageService


@lru_cache(maxsize=1)
def get_service() -> WebImageService:
    return WebImageService()


app = FastAPI(title="Publisher V2 Web Interface", version="0.1.0")

logger = logging.getLogger("publisher_v2.web")


def _get_correlation_id(request: Request) -> str:
    header = request.headers.get("X-Request-ID")
    if header:
        return header
    return str(uuid.uuid4())


@dataclass
class RequestTelemetry:
    correlation_id: str
    start_time: float


async def get_request_telemetry(request: Request) -> RequestTelemetry:
    """
    Derive a per-request correlation_id and capture a monotonic start time.

    The correlation_id is based on X-Request-ID when present, or a new UUID4.
    """
    correlation_id = _get_correlation_id(request)
    start_time = now_monotonic()
    # Expose on request.state so deeper layers can opt-in if needed.
    request.state.correlation_id = correlation_id
    return RequestTelemetry(correlation_id=correlation_id, start_time=start_time)


@app.on_event("startup")
async def _startup() -> None:
    # Minimal logging setup; reuse existing setup util
    level = logging.INFO
    if os.environ.get("WEB_DEBUG", "").lower() in ("1", "true", "yes"):
        level = logging.DEBUG
    setup_logging(level)
    log_json(logger, logging.INFO, "web_server_start")

    # Configure Auth0 if enabled
    # We do this here to ensure the OAuth registry is populated at startup
    from publisher_v2.web.routers.auth import configure_oauth
    
    # We need to load config to check if Auth0 is enabled
    # Using get_service() is safe here as it caches the result
    try:
        service = get_service()
        if service.config.auth0:
             configure_oauth(service.config)
             log_json(logger, logging.INFO, "auth0_configured")
    except Exception as e:
        log_json(logger, logging.WARNING, "auth0_config_error", error=str(e))


# Templates (server-rendered HTML with a small bit of JS)
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

# Session Middleware is required for OIDC state
# Fail fast if SECRET_KEY is missing in production-like environments
session_secret = os.environ.get("WEB_SESSION_SECRET") or os.environ.get("SECRET_KEY")
if not session_secret:
    # Allow dev fallback only if strictly local/debug, otherwise fail
    if os.environ.get("WEB_DEBUG", "").lower() in ("1", "true", "yes"):
        session_secret = "dev_secret_do_not_use_in_prod"
        logger.warning("Using insecure dev session secret!")
    else:
        raise RuntimeError("Missing WEB_SESSION_SECRET or SECRET_KEY env var for SessionMiddleware")

# Secure cookies default to True (prod), but can be disabled via env for local dev
secure_cookies = (os.environ.get("WEB_SECURE_COOKIES") or "true").lower() in ("1", "true", "yes", "on")
app.add_middleware(SessionMiddleware, secret_key=session_secret, https_only=secure_cookies)
app.include_router(auth_router.router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """
    Render the main HTML page.

    Web UI text defaults come from static, non-secret configuration so that
    labels and headings can be tuned or localized without code changes.
    """
    static_cfg = get_static_config().web_ui_text.values
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "web_ui_text": static_cfg,
        },
    )


@app.get(
    "/api/admin/status",
    response_model=AdminStatusResponse,
)
async def api_admin_status(request: Request) -> AdminStatusResponse:
    """
    Report whether the current request is in admin mode.
    """
    admin = is_admin_request(request)
    return AdminStatusResponse(admin=admin)


@app.post(
    "/api/admin/login",
    response_model=AdminStatusResponse,
    responses={401: {"model": ErrorResponse}},
)
async def api_admin_login(
    body: AdminLoginRequest,
    response: Response,
    request: Request,
) -> AdminStatusResponse:
    """
    Exchange a password for an admin session cookie.
    Only available if legacy password auth is configured.
    """
    actual_pass = get_admin_password()
    if not actual_pass:
        # Legacy login disabled
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Legacy login not enabled")

    if not verify_admin_password(body.password, actual_pass):
        # 401 enables the client to re-prompt
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid password")

    set_admin_cookie(response)
    log_json(logger, logging.INFO, "web_admin_login_success")
    return AdminStatusResponse(admin=True)


# Deprecated: use /api/auth/logout instead
# Kept temporarily if any older clients rely on it, but web UI uses new route.
@app.post(
    "/api/admin/logout",
    response_model=AdminStatusResponse,
    deprecated=True,
)
async def api_admin_logout(response: Response, request: Request) -> AdminStatusResponse:
    """
    Explicitly log out of admin mode by clearing the admin cookie.
    Also clears server-side session.
    """
    clear_admin_cookie(response)
    request.session.clear()
    log_json(logger, logging.INFO, "web_admin_logout")
    return AdminStatusResponse(admin=False)


def verify_view_permissions(
    request: Request,
    service: WebImageService = Depends(get_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> None:
    """
    Enforce permission policy for viewing images (list, details, random, thumbnails).
    
    Policy:
      - If FEATURE_AUTO_VIEW=true (default for local/dev), allow public access.
      - If FEATURE_AUTO_VIEW=false (default for prod/cloud), require Admin mode.
        - If Admin is not configured, fail closed (503).
    """
    features = service.config.features
    # Check if public view is allowed
    if getattr(features, "auto_view_enabled", False):
        return

    # Otherwise, strict admin check
    is_conf = is_admin_configured()
    logger.debug(f"verify_view_permissions: is_admin_configured={is_conf}")
    if not is_conf:
        # Admin required but not available -> Service Unavailable
        # Log telemetry if available
        if telemetry:
             log_json(
                logger,
                logging.WARNING,
                "view_permission_denied_admin_unconfigured",
                correlation_id=telemetry.correlation_id,
                path=request.url.path
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Image viewing requires admin mode but admin is not configured",
        )
    
    try:
        require_admin(request)
    except HTTPException:
        # Log the specific access denial
        if telemetry:
            log_json(
                logger,
                logging.WARNING,
                "view_permission_denied_admin_required",
                correlation_id=telemetry.correlation_id,
                path=request.url.path
            )
        raise


@app.get(
    "/api/images/list",
    response_model=ImageListResponse,
    dependencies=[Depends(verify_view_permissions)],
)
async def api_list_images(
    request: Request,
    response: Response,
    service: WebImageService = Depends(get_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> ImageListResponse:
    # Permissions checked by dependency
    # Service method returns dict, pydantic validates
    data = await service.list_images()
    return ImageListResponse(**data)


@app.get(
    "/api/images/random",
    response_model=ImageResponse,
    responses={404: {"model": ErrorResponse}},
    dependencies=[Depends(verify_view_permissions)],
)
async def api_get_random_image(
    request: Request,
    response: Response,
    service: WebImageService = Depends(get_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> ImageResponse:
    # Permissions checked by dependency
    try:
        img = await service.get_random_image()
        web_random_image_ms = elapsed_ms(telemetry.start_time)
        response.headers["X-Correlation-ID"] = telemetry.correlation_id
        log_json(
            logger,
            logging.INFO,
            "web_random_image",
            filename=img.filename,
            correlation_id=telemetry.correlation_id,
            web_random_image_ms=web_random_image_ms,
        )
        return img
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No images found")
    except Exception as exc:
        web_random_image_ms = elapsed_ms(telemetry.start_time)
        response.headers["X-Correlation-ID"] = telemetry.correlation_id
        log_json(
            logger,
            logging.ERROR,
            "web_random_image_error",
            error=str(exc),
            correlation_id=telemetry.correlation_id,
            web_random_image_ms=web_random_image_ms,
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")


@app.get(
    "/api/images/{filename}",
    response_model=ImageResponse,
    responses={404: {"model": ErrorResponse}},
    dependencies=[Depends(verify_view_permissions)],
)
async def api_get_image_details(
    filename: str,
    request: Request,
    response: Response,
    service: WebImageService = Depends(get_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> ImageResponse:
    # Permissions checked by dependency
    try:
        return await service.get_image_details(filename)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    except Exception as exc:
        log_json(logger, logging.ERROR, "web_get_image_error", error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")


@app.post(
    "/api/images/{filename}/analyze",
    response_model=AnalysisResponse,
    responses={404: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def api_analyze_image(
    filename: str,
    request: Request,
    response: Response,
    force_refresh: bool = Query(False),
    service: WebImageService = Depends(get_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> AnalysisResponse:
    await require_auth(request)
    if is_admin_configured():
        require_admin(request)
    try:
        resp = await service.analyze_and_caption(
            filename,
            correlation_id=telemetry.correlation_id,
            force_refresh=force_refresh,
        )
        web_analyze_ms = elapsed_ms(telemetry.start_time)
        response.headers["X-Correlation-ID"] = telemetry.correlation_id
        log_json(
            logger,
            logging.INFO,
            "web_analyze_complete",
            filename=filename,
            correlation_id=telemetry.correlation_id,
            web_analyze_ms=web_analyze_ms,
        )
        return resp
    except Exception as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
        web_analyze_ms = elapsed_ms(telemetry.start_time)
        response.headers["X-Correlation-ID"] = telemetry.correlation_id
        log_json(
            logger,
            logging.ERROR,
            "web_analyze_error",
            filename=filename,
            error=str(exc),
            correlation_id=telemetry.correlation_id,
            web_analyze_ms=web_analyze_ms,
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")


@app.post(
    "/api/images/{filename}/publish",
    response_model=PublishResponse,
    responses={404: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def api_publish_image(
    filename: str,
    request: Request,
    response: Response,
    body: Optional[PublishRequest] = None,
    service: WebImageService = Depends(get_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> PublishResponse:
    await require_auth(request)
    if is_admin_configured():
        require_admin(request)
    platforms = body.platforms if body else None
    try:
        resp = await service.publish_image(filename, platforms)
        web_publish_ms = elapsed_ms(telemetry.start_time)
        response.headers["X-Correlation-ID"] = telemetry.correlation_id
        log_json(
            logger,
            logging.INFO,
            "web_publish_complete",
            filename=filename,
            any_success=resp.any_success,
            archived=resp.archived,
            correlation_id=telemetry.correlation_id,
            web_publish_ms=web_publish_ms,
        )
        if not resp.any_success:
            # Still 200, but caller can inspect per-platform errors
            return resp
        return resp
    except Exception as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
        if isinstance(exc, PermissionError):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=str(exc),
            )
        web_publish_ms = elapsed_ms(telemetry.start_time)
        response.headers["X-Correlation-ID"] = telemetry.correlation_id
        log_json(
            logger,
            logging.ERROR,
            "web_publish_error",
            filename=filename,
            error=str(exc),
            correlation_id=telemetry.correlation_id,
            web_publish_ms=web_publish_ms,
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")


@app.post(
    "/api/images/{filename}/keep",
    response_model=CurationResponse,
    responses={
        404: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
async def api_keep_image(
    filename: str,
    request: Request,
    response: Response,
    service: WebImageService = Depends(get_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> CurationResponse:
    await require_auth(request)
    if is_admin_configured():
        require_admin(request)
    try:
        resp = await service.keep_image(filename)
        web_keep_ms = elapsed_ms(telemetry.start_time)
        response.headers["X-Correlation-ID"] = telemetry.correlation_id
        log_json(
            logger,
            logging.INFO,
            "web_keep_complete",
            filename=filename,
            destination_folder=resp.destination_folder,
            correlation_id=telemetry.correlation_id,
            web_keep_ms=web_keep_ms,
        )
        return resp
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except Exception as exc:
        web_keep_ms = elapsed_ms(telemetry.start_time)
        response.headers["X-Correlation-ID"] = telemetry.correlation_id
        log_json(
            logger,
            logging.ERROR,
            "web_keep_error",
            filename=filename,
            error=str(exc),
            correlation_id=telemetry.correlation_id,
            web_keep_ms=web_keep_ms,
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")


@app.post(
    "/api/images/{filename}/remove",
    response_model=CurationResponse,
    responses={
        404: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
async def api_remove_image(
    filename: str,
    request: Request,
    response: Response,
    service: WebImageService = Depends(get_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> CurationResponse:
    await require_auth(request)
    if is_admin_configured():
        require_admin(request)
    try:
        resp = await service.remove_image(filename)
        web_remove_ms = elapsed_ms(telemetry.start_time)
        response.headers["X-Correlation-ID"] = telemetry.correlation_id
        log_json(
            logger,
            logging.INFO,
            "web_remove_complete",
            filename=filename,
            destination_folder=resp.destination_folder,
            correlation_id=telemetry.correlation_id,
            web_remove_ms=web_remove_ms,
        )
        return resp
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        )
    except Exception as exc:
        web_remove_ms = elapsed_ms(telemetry.start_time)
        response.headers["X-Correlation-ID"] = telemetry.correlation_id
        log_json(
            logger,
            logging.ERROR,
            "web_remove_error",
            filename=filename,
            error=str(exc),
            correlation_id=telemetry.correlation_id,
            web_remove_ms=web_remove_ms,
        )
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")


class ThumbnailSizeParam(str, Enum):
    """Valid thumbnail size options."""
    w256h256 = "w256h256"
    w480h320 = "w480h320"
    w640h480 = "w640h480"
    w960h640 = "w960h640"
    w1024h768 = "w1024h768"


@app.get(
    "/api/images/{filename}/thumbnail",
    responses={
        200: {"content": {"image/jpeg": {}}},
        404: {"model": ErrorResponse},
    },
    dependencies=[Depends(verify_view_permissions)],
)
async def api_get_thumbnail(
    filename: str,
    request: Request,
    size: ThumbnailSizeParam = ThumbnailSizeParam.w960h640,
    service: WebImageService = Depends(get_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> Response:
    """
    Return a thumbnail of the specified image.

    Thumbnails are generated server-side by Dropbox and cached by
    the browser. This provides fast loading for previews while
    full-size images remain accessible via temp_url.

    Size options:
    - w256h256: Small icon (256×256)
    - w480h320: Mobile preview (480×320)
    - w640h480: Tablet preview (640×480)
    - w960h640: Desktop preview (960×640, default)
    - w1024h768: High-quality preview (1024×768)
    """
    # Permissions checked by dependency
    
    try:
        thumb_bytes = await service.get_thumbnail(filename, size=size.value)

        web_thumbnail_ms = elapsed_ms(telemetry.start_time)
        log_json(
            logger,
            logging.INFO,
            "web_thumbnail_served",
            filename=filename,
            size=size.value,
            bytes_served=len(thumb_bytes),
            correlation_id=telemetry.correlation_id,
            web_thumbnail_ms=web_thumbnail_ms,
        )

        return Response(
            content=thumb_bytes,
            media_type="image/jpeg",
            headers={
                "Cache-Control": "public, max-age=3600",
                "X-Correlation-ID": telemetry.correlation_id,
            },
        )
    except Exception as exc:
        msg = str(exc)
        if "not found" in msg.lower() or "path/not_found" in msg.lower():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Image not found",
            )

        web_thumbnail_ms = elapsed_ms(telemetry.start_time)
        log_json(
            logger,
            logging.ERROR,
            "web_thumbnail_error",
            filename=filename,
            error=str(exc),
            correlation_id=telemetry.correlation_id,
            web_thumbnail_ms=web_thumbnail_ms,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate thumbnail",
        )


@app.get("/api/config/publishers")
async def api_get_publishers_config(
    service: WebImageService = Depends(get_service)
) -> dict[str, bool]:
    """
    Return enablement state for all configured publishers.
    
    Returns a dict mapping publisher names to enabled state.
    No authentication required (non-sensitive configuration flags).
    """
    config = service.config
    return {
        "telegram": config.platforms.telegram_enabled and config.telegram is not None,
        "email": config.platforms.email_enabled and config.email is not None,
        "instagram": config.platforms.instagram_enabled and config.instagram is not None,
    }


@app.get("/api/config/features")
async def api_get_features_config(
    service: WebImageService = Depends(get_service),
) -> dict[str, Any]:
    """
    Return high-level product feature flags for the web UI.

    Values come from environment variables (FEATURE_ANALYZE_CAPTION, FEATURE_PUBLISH,
    FEATURE_KEEP_CURATE, FEATURE_REMOVE_CURATE) via the typed FeaturesConfig loaded
    in config.loader.
    """
    features = service.config.features
    
    # Determine auth mode
    auth_mode = get_auth_mode()

    return {
        "analyze_caption_enabled": features.analyze_caption_enabled,
        "publish_enabled": features.publish_enabled,
        "keep_enabled": features.keep_enabled,
        "remove_enabled": features.remove_enabled,
        "auto_view_enabled": getattr(features, "auto_view_enabled", False),
        "auth_mode": auth_mode,
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
