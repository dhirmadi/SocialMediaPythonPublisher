from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Request, status, Query
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from publisher_v2.config.static_loader import get_static_config
from publisher_v2.utils.logging import setup_logging, log_json, now_monotonic, elapsed_ms
from publisher_v2.web.auth import (
    require_auth,
    require_admin,
    is_admin_configured,
    get_admin_password,
    set_admin_cookie,
    clear_admin_cookie,
    is_admin_request,
)
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


# Templates (server-rendered HTML with a small bit of JS)
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)


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


@app.post(
    "/api/admin/login",
    response_model=AdminStatusResponse,
    responses={
        401: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def api_admin_login(
    payload: AdminLoginRequest,
    response: Response,
    service: WebImageService = Depends(get_service),
) -> AdminStatusResponse:
    """
    Simple admin login endpoint.

    Verifies the provided password against web_admin_pw and, on success,
    issues a short-lived admin cookie.
    """
    configured_password = get_admin_password()
    if not configured_password:
        log_json(logger, logging.WARNING, "web_admin_login_unconfigured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin mode not configured",
        )
    if not payload.password:
        log_json(logger, logging.WARNING, "web_admin_login_failure", reason="empty_password")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin password",
        )

    from publisher_v2.web.auth import verify_admin_password  # local import to avoid cycles

    if not verify_admin_password(payload.password, configured_password):
        log_json(logger, logging.WARNING, "web_admin_login_failure", reason="mismatch")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin password",
        )

    set_admin_cookie(response)
    log_json(logger, logging.INFO, "web_admin_login_success")

    # Proactively verify curation folders for admin convenience
    try:
        await service.verify_curation_folders()
    except Exception as exc:
        log_json(
            logger,
            logging.WARNING,
            "web_admin_login_folder_check_error",
            error=str(exc),
        )

    return AdminStatusResponse(admin=True)


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
    "/api/admin/logout",
    response_model=AdminStatusResponse,
)
async def api_admin_logout(response: Response) -> AdminStatusResponse:
    """
    Explicitly log out of admin mode by clearing the admin cookie.
    """
    clear_admin_cookie(response)
    log_json(logger, logging.INFO, "web_admin_logout")
    return AdminStatusResponse(admin=False)


@app.get(
    "/api/images/list",
    response_model=ImageListResponse,
)
async def api_list_images(
    request: Request,
    response: Response,
    service: WebImageService = Depends(get_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> ImageListResponse:
    features = service.config.features
    if not getattr(features, "auto_view_enabled", False):
        # reuse same logic as random image for permissions
        if not is_admin_configured():
             raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Image viewing requires admin mode but admin is not configured",
            )
        try:
            require_admin(request)
        except HTTPException:
            raise

    # Service method returns dict, pydantic validates
    data = await service.list_images()
    return ImageListResponse(**data)


@app.get(
    "/api/images/random",
    response_model=ImageResponse,
    responses={404: {"model": ErrorResponse}},
)
async def api_get_random_image(
    request: Request,
    response: Response,
    service: WebImageService = Depends(get_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> ImageResponse:
    # Enforce AUTO_VIEW semantics: when disabled, only admin may view images.
    features = service.config.features
    if not getattr(features, "auto_view_enabled", False):
        if not is_admin_configured():
            web_random_image_ms = elapsed_ms(telemetry.start_time)
            response.headers["X-Correlation-ID"] = telemetry.correlation_id
            log_json(
                logger,
                logging.WARNING,
                "web_random_image_admin_required_unconfigured",
                correlation_id=telemetry.correlation_id,
                web_random_image_ms=web_random_image_ms,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Image viewing requires admin mode but admin is not configured",
            )
        try:
            require_admin(request)
        except HTTPException:
            web_random_image_ms = elapsed_ms(telemetry.start_time)
            response.headers["X-Correlation-ID"] = telemetry.correlation_id
            log_json(
                logger,
                logging.WARNING,
                "web_random_image_admin_required",
                correlation_id=telemetry.correlation_id,
                web_random_image_ms=web_random_image_ms,
            )
            raise
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
)
async def api_get_image_details(
    filename: str,
    request: Request,
    response: Response,
    service: WebImageService = Depends(get_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> ImageResponse:
    # Enforce same permissions as random/list
    features = service.config.features
    if not getattr(features, "auto_view_enabled", False):
        if not is_admin_configured():
             raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Image viewing requires admin mode but admin is not configured",
            )
        try:
            require_admin(request)
        except HTTPException:
            raise

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
    # Respect AUTO_VIEW semantics (same as random image endpoint)
    features = service.config.features
    if not getattr(features, "auto_view_enabled", False):
        if not is_admin_configured():
            web_thumbnail_ms = elapsed_ms(telemetry.start_time)
            log_json(
                logger,
                logging.WARNING,
                "web_thumbnail_admin_required_unconfigured",
                filename=filename,
                correlation_id=telemetry.correlation_id,
                web_thumbnail_ms=web_thumbnail_ms,
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Image viewing requires admin mode but admin is not configured",
            )
        try:
            require_admin(request)
        except HTTPException:
            web_thumbnail_ms = elapsed_ms(telemetry.start_time)
            log_json(
                logger,
                logging.WARNING,
                "web_thumbnail_admin_required",
                filename=filename,
                correlation_id=telemetry.correlation_id,
                web_thumbnail_ms=web_thumbnail_ms,
            )
            raise

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
) -> dict[str, bool]:
    """
    Return high-level product feature flags for the web UI.

    Values come from environment variables (FEATURE_ANALYZE_CAPTION, FEATURE_PUBLISH,
    FEATURE_KEEP_CURATE, FEATURE_REMOVE_CURATE) via the typed FeaturesConfig loaded
    in config.loader.
    """
    features = service.config.features
    return {
        "analyze_caption_enabled": features.analyze_caption_enabled,
        "publish_enabled": features.publish_enabled,
        "keep_enabled": features.keep_enabled,
        "remove_enabled": features.remove_enabled,
        "auto_view_enabled": getattr(features, "auto_view_enabled", False),
    }


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}



