import logging

from fastapi import Request
from fastapi.responses import JSONResponse

from publisher_v2.config.runtime_settings import RuntimeSettings
from publisher_v2.config.source import get_config_source
from publisher_v2.core.exceptions import OrchestratorUnavailableError, TenantNotFoundError
from publisher_v2.web.settings import get_runtime_settings
from publisher_v2.web.tenant_factory import TenantServiceFactory

logger = logging.getLogger("publisher_v2.web")

# Process-wide tenant service factory. Deliberately *not* an ``lru_cache``:
# the middleware builds it from the injected settings while the lifespan
# shutdown must reach the very same instance without arguments, and
# ``lru_cache`` keys on the arguments (a factory built with defaults is a
# different cache entry, so shutdown would close an empty factory and evict
# the live one without ``aclose()`` — the #86 cleanup would silently stop).
_FACTORY: TenantServiceFactory | None = None


def _tenant_service_factory(settings: RuntimeSettings) -> TenantServiceFactory:
    """Return the process-wide factory, building it once from the injected settings (#143)."""
    global _FACTORY
    if _FACTORY is None:
        _FACTORY = TenantServiceFactory(
            max_size=settings.tenant_service_cache_max_size,
            ttl_seconds=settings.tenant_service_ttl_seconds,
            settings=settings,
        )
    return _FACTORY


def _existing_tenant_service_factory() -> TenantServiceFactory | None:
    """The live factory, or None when no request ever built one (shutdown path)."""
    return _FACTORY


def reset_tenant_service_factory() -> TenantServiceFactory | None:
    """Drop the process-wide factory and return it, so the caller can shut it down.

    Test hook only. Dropping a factory that still holds live services leaks their
    storage/HTTP clients and their un-flushed storage-ops metrics — the caller is
    responsible for ``await factory.shutdown()`` on the returned value.
    """
    global _FACTORY
    factory, _FACTORY = _FACTORY, None
    return factory


async def tenant_middleware(request: Request, call_next):
    """
    Resolve per-request runtime config and attach a WebImageService to request.state.
    """
    # Skip all health endpoints (liveness/readiness probes should never require tenant resolution)
    if request.url.path.startswith("/health"):
        return await call_next(request)

    # Only engage multi-tenant orchestration when explicitly configured.
    settings = get_runtime_settings(request)
    if settings.is_standalone:
        return await call_next(request)

    try:
        host = request.headers.get("host", "")
        source = get_config_source()
        runtime = await source.get_config(host)
        factory = _tenant_service_factory(settings)
        service = await factory.get_service(source, runtime)

        request.state.host = runtime.host
        request.state.tenant = runtime.tenant
        request.state.config = runtime.config
        request.state.web_service = service
    except TenantNotFoundError:
        return JSONResponse({"error": "Not found"}, status_code=404)
    except OrchestratorUnavailableError:
        return JSONResponse({"error": "Service unavailable"}, status_code=503)

    return await call_next(request)
