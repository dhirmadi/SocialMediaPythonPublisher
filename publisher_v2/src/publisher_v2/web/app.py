"""FastAPI application for the Publisher V2 admin UI and its JSON API.

Owns app construction: the lifespan that snapshots runtime settings onto ``app.state``
once per process (#143), the middleware stack (tenant resolution, CSRF, security headers,
sessions), the health probes, and the admin/auth and view-permission endpoints. Routers
for the library and image endpoints are mounted here; per-request services come from
:mod:`publisher_v2.web.dependencies`.
"""

import asyncio
import json
import logging
import os
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, NoReturn

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, Response
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from publisher_v2.config.runtime_settings import load_runtime_settings
from publisher_v2.config.source import get_config_source
from publisher_v2.config.static_loader import get_static_config
from publisher_v2.core.exceptions import (
    AlreadyPublishedError,
    CaptionCoverageError,
    OrchestratorUnavailableError,
    PublishInProgressError,
)
from publisher_v2.utils.logging import elapsed_ms, log_json, now_monotonic, setup_logging
from publisher_v2.web.auth import (
    clear_admin_cookie,
    is_admin_configured,
    is_admin_request,
    require_admin,
    require_auth,
    revoke_admin_request,
)
from publisher_v2.web.dependencies import get_request_service, get_service
from publisher_v2.web.middleware import tenant_middleware
from publisher_v2.web.middleware_csrf import CSRFMiddleware
from publisher_v2.web.middleware_security import SecurityHeadersMiddleware
from publisher_v2.web.models import (
    AdminStatusResponse,
    AnalysisResponse,
    CurationResponse,
    ErrorResponse,
    ImageListResponse,
    ImageResponse,
    PublishRequest,
    PublishResponse,
    VoiceProfileResponse,
    VoiceProfileUpdateRequest,
)
from publisher_v2.web.rate_limit import SlidingWindowLimiter, remote_ip
from publisher_v2.web.routers import auth as auth_router
from publisher_v2.web.routers import library as library_router
from publisher_v2.web.service import WebImageService
from publisher_v2.web.settings import get_runtime_settings

__all__ = [
    "app",
    "get_service",  # legacy import path used by tests and older code
]

# Module-level limiters (process-local). Cost endpoints: 10 per minute per IP,
# 100 per hour per IP (per-admin keys layered on top).
_ANALYZE_LIMITER_MIN = SlidingWindowLimiter(window_seconds=60, max_events=10, label="analyze/min")
_ANALYZE_LIMITER_HOUR = SlidingWindowLimiter(window_seconds=3600, max_events=100, label="analyze/hour")
_PUBLISH_LIMITER_MIN = SlidingWindowLimiter(window_seconds=60, max_events=10, label="publish/min")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Lifespan context manager for FastAPI app startup and shutdown events.

    This replaces the deprecated @app.on_event("startup") decorator.
    """
    # Startup logic
    level = logging.INFO
    if os.environ.get("WEB_DEBUG", "").lower() in ("1", "true", "yes"):
        level = logging.DEBUG
    setup_logging(level)

    _logger = logging.getLogger("publisher_v2.web")
    log_json(_logger, logging.INFO, "web_server_start")

    # #129: on Heroku the router is not loopback, so uvicorn never rewrites
    # request.url.scheme and every cookie-bearing POST under /api fails the CSRF
    # same-origin check. Deriving the scheme ourselves only happens when the
    # trust flag is set, so a dyno provisioned without it reproduces the outage
    # silently. Say it once, at startup, where an operator will see it.
    # Startup, so there is no request to read the snapshot from; this is one of
    # the reads #143 allows outside a request path.
    if os.environ.get("DYNO") and not load_runtime_settings().trust_forwarded_for:
        log_json(
            _logger,
            logging.WARNING,
            "forwarded_headers_untrusted_on_heroku",
            detail=(
                "DYNO is set but WEB_TRUST_FORWARDED_FOR is not enabled; the Heroku router's "
                "X-Forwarded-Proto will be ignored and browser POSTs under /api will return 403"
            ),
        )
    # #143: parse the runtime tunables once per process; request paths read
    # them from app.state instead of re-parsing the environment.
    app.state.runtime_settings = load_runtime_settings()

    # Auth0 is configured lazily on first auth route call.
    # Avoid forcing a full ApplicationConfig load here because orchestrator mode
    # may not have standalone secrets configured at process start.

    # Initialise caption history DB (optional — graceful degradation if not configured)
    from publisher_v2.db import init_db

    init_db(app.state.runtime_settings)

    # #144: resolve the standalone storage origin once, so the CSP on a cold
    # process's first page render already names it. Orchestrated requests use
    # their own tenant config instead.
    app.state.csp_storage_origins = []
    try:
        from publisher_v2.web.middleware_security import storage_origins_for_config

        # Building the standalone service is synchronous (config load, storage
        # client, DB wiring), so keep it off the event loop.
        service = await asyncio.to_thread(get_service)
        app.state.csp_storage_origins = storage_origins_for_config(service.config)
    except Exception as exc:
        # Orchestrated instances have no standalone config, so this fails on
        # EVERY boot there by design and the CSP correctly falls back to
        # 'self'. DEBUG without a traceback: at INFO this reads as a fault in
        # the deployment where it is the expected path.
        _logger.debug("csp_storage_origin_unresolved: %s", type(exc).__name__)

    yield

    # Shutdown: dispose the caption history DB engine, flush tenant services,
    # and only then drop the process settings (#143).
    from publisher_v2.db import dispose_engine

    try:
        await dispose_engine()
    except Exception:
        _logger.warning("caption_history_db_dispose_failed", exc_info=True)

    # Close the shared httpx client used by Vision image downloads.
    try:
        from publisher_v2.services._http import aclose_shared_client

        await aclose_shared_client()
    except Exception:
        _logger.warning("shared_http_client_close_failed", exc_info=True)

    # Shutdown: flush remaining storage ops metrics for all cached tenants.
    # Use the *existing* factory: never build one just to close it.
    from publisher_v2.web.middleware import reset_tenant_service_factory

    try:
        # Dropped as well as shut down: the factory carries this app's settings
        # snapshot (its cache size and TTL came from it), so leaving the global
        # in place would hand the next app built in this process a dead factory
        # holding the previous app's settings — the same leak the
        # ``app.state.runtime_settings`` reset below prevents.
        #
        # A request arriving between the drop and the shutdown would build a
        # second factory whose services this shutdown never closes. Reproduced
        # for this shape, and reasoned for the previous one, which leaked the
        # same single service (a request after ``shutdown()`` repopulated the
        # factory it had just cleared); uvicorn also drains in-flight requests
        # before emitting lifespan.shutdown. A ``_SHUTTING_DOWN`` gate would
        # close the window, either by handing that request the dropped factory
        # (serving it from closed resources) or by refusing it with a 503.
        factory = reset_tenant_service_factory()
        if factory is not None:
            await factory.shutdown()
    except Exception:
        _logger.warning("storage_ops_shutdown_flush_failed", exc_info=True)

    # Cleared last, after the DB dispose and the tenant flush above. A request
    # still in flight past this point falls back to a fresh env parse, which
    # yields the same values; leaving it set would leak one app's snapshot into
    # the next app built in the same process (#143).
    app.state.runtime_settings = None


# PUB-048 (AC5): FastAPI's interactive docs and schema are disabled, so the
# route table and the upload contract are not readable anonymously on every
# tenant host. With these set to None no routes are registered for those
# paths at all, and they fall through to the app's default 404.
app = FastAPI(
    title="Publisher V2 Web Interface",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

logger = logging.getLogger("publisher_v2.web")


# #144: fullmatch, not match — "$" also matches just before a trailing newline,
# so "abc\n" passed and the newline reached the correlation id and every log line.
_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,128}")


def _get_correlation_id(request: Request) -> str:
    """Echo X-Request-ID only when it is short and log/header-safe (#87 SEC-12)."""
    header = request.headers.get("X-Request-ID")
    if header and _REQUEST_ID_RE.fullmatch(header):
        return header
    return str(uuid.uuid4())


@dataclass(frozen=True, slots=True)
class RequestTelemetry:
    correlation_id: str
    start_time: float


async def get_request_telemetry(request: Request) -> RequestTelemetry:
    """Derive a per-request correlation_id and capture a monotonic start time.

    The correlation_id is based on X-Request-ID when present, or a new UUID4.
    """
    correlation_id = _get_correlation_id(request)
    start_time = now_monotonic()
    # Expose on request.state so deeper layers can opt-in if needed.
    request.state.correlation_id = correlation_id
    return RequestTelemetry(correlation_id=correlation_id, start_time=start_time)


async def endpoint_telemetry(
    event_name: str,
    response: Response,
    telemetry: RequestTelemetry,
    **extra_log_kwargs: Any,
) -> None:
    """Log success telemetry and set the correlation header on the response."""
    ms = elapsed_ms(telemetry.start_time)
    response.headers["X-Correlation-ID"] = telemetry.correlation_id
    log_json(
        logger,
        logging.INFO,
        event_name,
        correlation_id=telemetry.correlation_id,
        **{f"{event_name}_ms": ms},
        **extra_log_kwargs,
    )


def raise_for_service_error(
    exc: Exception, event_name: str, response: Response, telemetry: RequestTelemetry
) -> NoReturn:
    """Map service-layer exceptions to HTTP responses, with error telemetry.

    The exception text is kept server-side (logged with correlation_id) and is
    NOT included in the response body, since exception strings can carry
    secrets (SMTP auth strings, Telegram URLs with bot tokens, stack frames).
    The correlation_id is returned so an operator can match an error to logs.
    """
    # Route by typed exception first — these don't leak sensitive context.
    if isinstance(exc, FileNotFoundError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")
    if isinstance(exc, PermissionError):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")
    if isinstance(exc, PublishInProgressError):
        # #139: a second click while the first publish is still running.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Publish already in progress")
    if isinstance(exc, AlreadyPublishedError):
        # #139: no-DB installs refuse to publish the same image twice.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Image already published")
    if isinstance(exc, CaptionCoverageError):
        # #147: a per-platform caption dict that does not cover the enabled set.
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    msg = str(exc)
    if "not found" in msg.lower() or "path/not_found" in msg.lower():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    ms = elapsed_ms(telemetry.start_time)
    response.headers["X-Correlation-ID"] = telemetry.correlation_id
    log_json(
        logger,
        logging.ERROR,
        f"{event_name}_error",
        error=msg,
        error_type=type(exc).__name__,
        correlation_id=telemetry.correlation_id,
        **{f"{event_name}_ms": ms},
    )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=f"Internal error (ref {telemetry.correlation_id})",
    )


# Templates (server-rendered HTML with a small bit of JS)
templates_dir = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=templates_dir)

# Session Middleware is required for OIDC state
# Fail fast if SECRET_KEY is missing in production-like environments
session_secret = os.environ.get("WEB_SESSION_SECRET") or os.environ.get("SECRET_KEY")
if not session_secret:
    # #87 (SEC-5): the insecure fallback requires its own explicit opt-in —
    # WEB_DEBUG is a logging flag and must not weaken the signing secret.
    if os.environ.get("WEB_DEV_INSECURE_SECRET", "").lower() in ("1", "true", "yes", "on"):
        session_secret = "dev_secret_do_not_use_in_prod"  # nosec B105 — placeholder behind an explicit opt-in, and it logs a warning
        logger.warning("Using insecure dev session secret!")
    else:
        raise RuntimeError("Missing WEB_SESSION_SECRET or SECRET_KEY env var for SessionMiddleware")

# #87 (SEC-12): register the tenant middleware FIRST so it runs INSIDE the
# security-header middleware — later add_middleware calls wrap earlier ones,
# and the tenant 404/503 JSON responses must carry CSP/nosniff too.
app.middleware("http")(tenant_middleware)

# Secure cookies default to True (prod), but can be disabled via env for local dev
secure_cookies = load_runtime_settings().secure_cookies
app.add_middleware(SessionMiddleware, secret_key=session_secret, https_only=secure_cookies)

# Defense-in-depth headers + CSRF protection. Order matters: SecurityHeaders is
# outermost so even error responses receive headers; CSRF runs after session
# middleware so it can read cookies if needed.

app.add_middleware(CSRFMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(auth_router.router)
app.include_router(library_router.router)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    """Render the main HTML page.

    Web UI text defaults come from static, non-secret configuration so that
    labels and headings can be tuned or localized without code changes.
    """
    static_cfg = get_static_config().web_ui_text.values
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "web_ui_text": static_cfg,
            # #91 (SEC-8): per-request CSP nonce set by SecurityHeadersMiddleware.
            "csp_nonce": getattr(request.state, "csp_nonce", ""),
        },
    )


@app.get("/health/live")
async def health_live() -> dict[str, str]:
    """Liveness probe: returns 200 if process is running."""
    return {"status": "ok"}


@app.get("/health/ready")
async def health_ready(request: Request) -> Response:
    """Report readiness, returning 503 when a required dependency is unreachable.

    Readiness probe:
    - env-first mode: always ready
    - orchestrator mode: requires orchestrator connectivity (404 is acceptable)
    - caption history DB: checked when configured
    """
    is_standalone = get_runtime_settings(request).is_standalone

    body: dict[str, Any] = {
        "status": "ok",
        "mode": "standalone" if is_standalone else "orchestrated",
    }

    if not is_standalone:
        try:
            source = get_config_source()
            if hasattr(source, "check_connectivity"):
                await source.check_connectivity()  # type: ignore[attr-defined]
        except OrchestratorUnavailableError:
            return Response(
                content='{"status":"not_ready","reason":"orchestrator_unavailable"}',
                media_type="application/json",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    from publisher_v2.db import check_connectivity as db_check
    from publisher_v2.db import is_db_available

    if is_db_available():
        db_ok = await db_check()
        body["caption_history_db"] = "ok" if db_ok else "unavailable"
        if not db_ok:
            body["status"] = "degraded"
            return Response(
                content=json.dumps(body),
                media_type="application/json",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

    return Response(content=json.dumps(body), media_type="application/json")


@app.get(
    "/api/admin/status",
    response_model=AdminStatusResponse,
)
async def api_admin_status(request: Request) -> AdminStatusResponse:
    """Report whether the current request is in admin mode."""
    admin = is_admin_request(request)
    return AdminStatusResponse(admin=admin)


@app.post("/api/auth/logout", response_model=AdminStatusResponse)
async def api_auth_logout(response: Response, request: Request) -> AdminStatusResponse:
    """Log out of admin mode (#91 SEC-8): POST under /api so CSRF applies."""
    revoke_admin_request(request)
    clear_admin_cookie(response)
    request.session.clear()
    log_json(logger, logging.INFO, "web_admin_logout")
    return AdminStatusResponse(admin=False)


# Deprecated: use /api/auth/logout instead
# Kept temporarily if any older clients rely on it, but web UI uses new route.
@app.post(
    "/api/admin/logout",
    response_model=AdminStatusResponse,
    deprecated=True,
)
async def api_admin_logout(response: Response, request: Request) -> AdminStatusResponse:
    """Log out of admin mode by clearing the admin cookie.

    Deprecated in favour of ``POST /api/auth/logout``. Also revokes the admin request
    marker and clears the server-side session.
    """
    revoke_admin_request(request)
    clear_admin_cookie(response)
    request.session.clear()
    log_json(logger, logging.INFO, "web_admin_logout")
    return AdminStatusResponse(admin=False)


def verify_view_permissions(
    request: Request,
    service: WebImageService = Depends(get_request_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> None:
    """Enforce permission policy for viewing images (list, details, random, thumbnails).

    Policy:
      - If FEATURE_AUTO_VIEW=true (default for local/dev), allow public access.
      - If FEATURE_AUTO_VIEW=false (default for prod/cloud), require Admin mode.
        - If Admin is not configured, fail closed (503).
    """
    features = service.config.features
    # Check if public view is allowed
    if features.auto_view_enabled:
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
                path=request.url.path,
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
                path=request.url.path,
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
    service: WebImageService = Depends(get_request_service),
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
    service: WebImageService = Depends(get_request_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> ImageResponse:
    try:
        img = await service.get_random_image()
        await endpoint_telemetry("web_random_image", response, telemetry, filename=img.filename)
        return img
    except Exception as exc:
        raise_for_service_error(exc, "web_random_image", response, telemetry)


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
    service: WebImageService = Depends(get_request_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> ImageResponse:
    try:
        result = await service.get_image_details(filename)
        await endpoint_telemetry("web_get_image", response, telemetry, filename=filename)
        return result
    except Exception as exc:
        raise_for_service_error(exc, "web_get_image", response, telemetry)


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
    service: WebImageService = Depends(get_request_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> AnalysisResponse:
    await require_auth(request)
    # #137: always admin-gated; Auth0 is the only admin login (503 when not configured).
    require_admin(request)
    # Cost guard: vision + caption calls are expensive. Limit per IP across
    # both short (per-minute) and long (per-hour) windows.
    ip = remote_ip(request)
    _ANALYZE_LIMITER_MIN.check(ip)
    _ANALYZE_LIMITER_HOUR.check(ip)
    try:
        resp = await service.analyze_and_caption(
            filename,
            correlation_id=telemetry.correlation_id,
            force_refresh=force_refresh,
        )
        await endpoint_telemetry("web_analyze", response, telemetry, filename=filename)
        return resp
    except Exception as exc:
        raise_for_service_error(exc, "web_analyze", response, telemetry)


@app.post(
    "/api/images/{filename}/publish",
    response_model=PublishResponse,
    responses={
        404: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def api_publish_image(
    filename: str,
    request: Request,
    response: Response,
    body: PublishRequest | None = None,
    service: WebImageService = Depends(get_request_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> PublishResponse:
    await require_auth(request)
    # #137: always admin-gated; Auth0 is the only admin login (503 when not configured).
    require_admin(request)
    _PUBLISH_LIMITER_MIN.check(remote_ip(request))
    platforms = body.platforms if body else None
    raw_caption = body.caption if body else None
    caption_override = raw_caption.strip() if raw_caption and raw_caption.strip() else None
    # #147: per-platform captions from the UI editors; blank entries are dropped.
    raw_captions = body.captions if body else None
    caption_overrides = {p: c.strip() for p, c in (raw_captions or {}).items() if c and c.strip()} or None
    # #147: the "must cover exactly the enabled platforms" check lives in
    # WebImageService.publish_image, so every caller gets it; its
    # CaptionCoverageError is mapped to 400 below. Duplicating it here would
    # leave that mapping untested while looking covered.
    try:
        if caption_overrides:
            resp = await service.publish_image(
                filename, platforms, caption_override=caption_override, caption_overrides=caption_overrides
            )
        else:
            resp = await service.publish_image(filename, platforms, caption_override=caption_override)
        await endpoint_telemetry(
            "web_publish",
            response,
            telemetry,
            filename=filename,
            any_success=resp.any_success,
            archived=resp.archived,
        )
        return resp
    except Exception as exc:
        raise_for_service_error(exc, "web_publish", response, telemetry)


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
    service: WebImageService = Depends(get_request_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> CurationResponse:
    await require_auth(request)
    # #137: always admin-gated; Auth0 is the only admin login (503 when not configured).
    require_admin(request)
    try:
        resp = await service.keep_image(filename)
        await endpoint_telemetry(
            "web_keep",
            response,
            telemetry,
            filename=filename,
            destination_folder=resp.destination_folder,
        )
        return resp
    except Exception as exc:
        raise_for_service_error(exc, "web_keep", response, telemetry)


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
    service: WebImageService = Depends(get_request_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> CurationResponse:
    await require_auth(request)
    # #137: always admin-gated; Auth0 is the only admin login (503 when not configured).
    require_admin(request)
    try:
        resp = await service.remove_image(filename)
        await endpoint_telemetry(
            "web_remove",
            response,
            telemetry,
            filename=filename,
            destination_folder=resp.destination_folder,
        )
        return resp
    except Exception as exc:
        raise_for_service_error(exc, "web_remove", response, telemetry)


@app.post(
    "/api/images/{filename}/delete",
    response_model=CurationResponse,
    responses={
        404: {"model": ErrorResponse},
        401: {"model": ErrorResponse},
        403: {"model": ErrorResponse},
    },
)
async def api_delete_image(
    filename: str,
    request: Request,
    response: Response,
    service: WebImageService = Depends(get_request_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> CurationResponse:
    await require_auth(request)
    # #137: always admin-gated; Auth0 is the only admin login (503 when not configured).
    require_admin(request)
    try:
        resp = await service.delete_image(filename)
        await endpoint_telemetry(
            "web_delete",
            response,
            telemetry,
            filename=filename,
            destination_folder=resp.destination_folder,
        )
        return resp
    except Exception as exc:
        raise_for_service_error(exc, "web_delete", response, telemetry)


class ThumbnailSizeParam(StrEnum):
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
    response: Response,
    size: ThumbnailSizeParam = ThumbnailSizeParam.w960h640,
    service: WebImageService = Depends(get_request_service),
    telemetry: RequestTelemetry = Depends(get_request_telemetry),
) -> Response:
    """Return a thumbnail of the specified image.

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
        await endpoint_telemetry(
            "web_thumbnail",
            response,
            telemetry,
            filename=filename,
            size=size.value,
            bytes_served=len(thumb_bytes),
        )
        return Response(
            content=thumb_bytes,
            media_type="image/jpeg",
            headers={
                # #87 (SEC-7): the route is permission-gated — a shared cache
                # must never serve one viewer's thumbnail to another.
                "Cache-Control": "private, max-age=3600",
                "Vary": "Cookie",
                "X-Correlation-ID": telemetry.correlation_id,
            },
        )
    except Exception as exc:
        from PIL import Image as _PILImage

        if isinstance(exc, _PILImage.DecompressionBombError):
            # #90: an oversized source image is a client-data problem, not a 500.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Source image exceeds the allowed pixel count",
            ) from exc
        raise_for_service_error(exc, "web_thumbnail", response, telemetry)


@app.get("/api/config/publishers")
async def api_get_publishers_config(service: WebImageService = Depends(get_request_service)) -> dict[str, bool]:
    """Return enablement state for all configured publishers.

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
    service: WebImageService = Depends(get_request_service),
) -> dict[str, Any]:
    """Return high-level product feature flags for the web UI.

    Values come from environment variables (FEATURE_ANALYZE_CAPTION, FEATURE_PUBLISH,
    FEATURE_KEEP_CURATE, FEATURE_REMOVE_CURATE) via the typed FeaturesConfig loaded
    in config.loader.
    """
    features = service.config.features

    # #137: Auth0 is the only admin login; the (tenant-scoped) service config decides.
    auth_mode = "auth0" if service.config.auth0 is not None else "none"

    # #97 stage 1: resolved at config load (env override, else auto for managed storage)
    library_enabled = service.config.features.library_enabled

    storage_provider = "managed" if service.config.managed is not None else "dropbox"

    return {
        "analyze_caption_enabled": features.analyze_caption_enabled,
        "publish_enabled": features.publish_enabled,
        "keep_enabled": features.keep_enabled,
        "remove_enabled": features.remove_enabled,
        "delete_enabled": features.delete_enabled,
        "auto_view_enabled": features.auto_view_enabled,
        "library_enabled": library_enabled,
        "auth_mode": auth_mode,
        "storage_provider": storage_provider,
    }


@app.get("/api/config/voice-profile", response_model=VoiceProfileResponse)
async def api_get_voice_profile(
    request: Request,
    service: WebImageService = Depends(get_request_service),
) -> VoiceProfileResponse:
    """PUB-029 AC-06: return current runtime voice profile (admin only)."""
    # PUB-048 (AC1): both guards, like every other admin route. Order is
    # inverted relative to those routes on purpose: `require_admin` runs
    # first so its 403 ("Admin mode disabled for this tenant" / "Admin
    # privileges required") keeps winning over `require_auth`'s 401/503 for
    # a missing or cross-tenant cookie, which is the precedence this item's
    # Implementation Notes require. Strict mode is enforced inside
    # `require_admin` itself, so running it first loses no coverage.
    require_admin(request)
    await require_auth(request)
    config = service.config
    return VoiceProfileResponse(
        voice_profile=config.content.voice_profile,
        enabled=config.features.voice_matching_enabled,
    )


@app.post("/api/config/voice-profile", response_model=VoiceProfileResponse)
async def api_set_voice_profile(
    request: Request,
    body: VoiceProfileUpdateRequest,
    service: WebImageService = Depends(get_request_service),
) -> VoiceProfileResponse:
    """PUB-029 AC-06: update runtime voice profile in-memory (admin only).

    Updates the active service config for this process; does not persist back
    to the orchestrator. Empty list clears the profile (stored as ``None``).
    """
    # PUB-048 (AC1): both guards, like every other admin route. Order is
    # inverted relative to those routes on purpose: `require_admin` runs
    # first so its 403 ("Admin mode disabled for this tenant" / "Admin
    # privileges required") keeps winning over `require_auth`'s 401/503 for
    # a missing or cross-tenant cookie, which is the precedence this item's
    # Implementation Notes require. Strict mode is enforced inside
    # `require_admin` itself, so running it first loses no coverage.
    require_admin(request)
    await require_auth(request)
    from pydantic import ValidationError as _PydValidation

    from publisher_v2.config.schema import ContentConfig

    new_value: list[str] | None = body.voice_profile if body.voice_profile else None
    try:
        # Validate via the schema rules (length, non-empty entries) without mutating yet.
        ContentConfig(voice_profile=new_value)
    except _PydValidation as exc:
        raise HTTPException(status_code=400, detail=f"Invalid voice_profile: {exc.errors()[0].get('msg')}") from exc

    # Mutate in place. ContentConfig is a Pydantic model; assignment works.
    service.config.content.voice_profile = new_value

    # #131: matching defaults on when a tenant has a profile, and that default
    # is derived at load time. A profile added here would otherwise leave
    # matching off until the process restarted — the response would report a
    # stored profile alongside `enabled: false`. Only the derived default is
    # re-evaluated: an explicit flag, either way, still wins.
    # `model_fields_set` distinguishes a flag an operator set from one derived
    # at load time; the loader and the ApplicationConfig validator both leave a
    # derived value unset, so this branch fires only when nobody chose.
    features = service.config.features
    if "voice_matching_enabled" not in features.model_fields_set:
        features.voice_matching_enabled = bool(new_value)
        # Assigning marks the field as explicitly set, which would make the
        # NEXT profile change look operator-configured and skip this branch.
        # Keeping it derived means clearing the profile turns matching off
        # again, just as adding one turned it on.
        features.model_fields_set.discard("voice_matching_enabled")

    return VoiceProfileResponse(
        voice_profile=service.config.content.voice_profile,
        enabled=service.config.features.voice_matching_enabled,
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
