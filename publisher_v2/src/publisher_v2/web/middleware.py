from __future__ import annotations

import logging
from functools import lru_cache

from fastapi import Request
from fastapi.responses import JSONResponse

from publisher_v2.config.source import get_config_source
from publisher_v2.core.exceptions import TenantNotFoundError, OrchestratorUnavailableError
from publisher_v2.services.tenant_factory import TenantServiceFactory
from publisher_v2.web.service import WebImageService


logger = logging.getLogger("publisher_v2.web")


@lru_cache(maxsize=1)
def _tenant_service_factory() -> TenantServiceFactory:
    # Defaults can be overridden by env vars (see Story 06)
    import os

    max_size = int(os.environ.get("TENANT_SERVICE_CACHE_MAX_SIZE") or "1000")
    ttl = int(os.environ.get("TENANT_SERVICE_TTL_SECONDS") or "600")
    return TenantServiceFactory(max_size=max_size, ttl_seconds=ttl)




async def tenant_middleware(request: Request, call_next):
    """
    Resolve per-request runtime config and attach a WebImageService to request.state.
    """
    if request.url.path.startswith("/health/"):
        return await call_next(request)

    # Only engage multi-tenant orchestration when explicitly configured.
    import os

    override = (os.environ.get("CONFIG_SOURCE") or "").strip().lower()
    if override == "env" or not os.environ.get("ORCHESTRATOR_BASE_URL"):
        return await call_next(request)

    try:
        host = request.headers.get("host", "")
        source = get_config_source()
        runtime = await source.get_config(host)
        service = await _tenant_service_factory().get_service(source, runtime)

        request.state.host = runtime.host
        request.state.tenant = runtime.tenant
        request.state.config = runtime.config
        request.state.web_service = service
    except TenantNotFoundError:
        return JSONResponse({"error": "Not found"}, status_code=404)
    except OrchestratorUnavailableError:
        return JSONResponse({"error": "Service unavailable"}, status_code=503)

    return await call_next(request)


