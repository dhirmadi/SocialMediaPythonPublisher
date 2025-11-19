from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional

from fastapi import FastAPI, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates

from publisher_v2.utils.logging import setup_logging, log_json
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
    AnalysisResponse,
    PublishResponse,
    PublishRequest,
    ErrorResponse,
    AdminLoginRequest,
    AdminStatusResponse,
)
from publisher_v2.web.service import WebImageService


@lru_cache(maxsize=1)
def get_service() -> WebImageService:
    return WebImageService()


app = FastAPI(title="Publisher V2 Web Interface", version="0.1.0")

logger = logging.getLogger("publisher_v2.web")


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
    """
    return templates.TemplateResponse("index.html", {"request": request})


@app.post(
    "/api/admin/login",
    response_model=AdminStatusResponse,
    responses={
        401: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def api_admin_login(payload: AdminLoginRequest, response: Response) -> AdminStatusResponse:
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
    "/api/images/random",
    response_model=ImageResponse,
    responses={404: {"model": ErrorResponse}},
)
async def api_get_random_image(service: WebImageService = Depends(get_service)) -> ImageResponse:
    try:
        img = await service.get_random_image()
        log_json(logger, logging.INFO, "web_random_image", filename=img.filename)
        return img
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No images found")
    except Exception as exc:
        log_json(logger, logging.ERROR, "web_random_image_error", error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")


@app.post(
    "/api/images/{filename}/analyze",
    response_model=AnalysisResponse,
    responses={404: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def api_analyze_image(
    filename: str,
    request: Request,
    service: WebImageService = Depends(get_service),
) -> AnalysisResponse:
    await require_auth(request)
    if is_admin_configured():
        require_admin(request)
    try:
        resp = await service.analyze_and_caption(filename)
        log_json(logger, logging.INFO, "web_analyze_complete", filename=filename)
        return resp
    except Exception as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
        log_json(logger, logging.ERROR, "web_analyze_error", filename=filename, error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")


@app.post(
    "/api/images/{filename}/publish",
    response_model=PublishResponse,
    responses={404: {"model": ErrorResponse}, 401: {"model": ErrorResponse}},
)
async def api_publish_image(
    filename: str,
    request: Request,
    body: Optional[PublishRequest] = None,
    service: WebImageService = Depends(get_service),
) -> PublishResponse:
    await require_auth(request)
    if is_admin_configured():
        require_admin(request)
    platforms = body.platforms if body else None
    try:
        resp = await service.publish_image(filename, platforms)
        log_json(
            logger,
            logging.INFO,
            "web_publish_complete",
            filename=filename,
            any_success=resp.any_success,
            archived=resp.archived,
        )
        if not resp.any_success:
            # Still 200, but caller can inspect per-platform errors
            return resp
        return resp
    except Exception as exc:
        msg = str(exc)
        if "not found" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
        log_json(logger, logging.ERROR, "web_publish_error", filename=filename, error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal error")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}



