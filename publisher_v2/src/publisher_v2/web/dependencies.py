from __future__ import annotations

from functools import lru_cache

from fastapi import Request

from publisher_v2.web.service import WebImageService


@lru_cache(maxsize=1)
def get_service() -> WebImageService:
    """
    Backward-compatible standalone singleton.

    Many tests override this dependency or call get_service.cache_clear().
    """
    return WebImageService()


def get_request_service(request: Request) -> WebImageService:
    """
    Request-scoped dependency for WebImageService.

    - In orchestrator mode, tenant_middleware attaches request.state.web_service.
    - Otherwise, fall back to the standalone singleton get_service().
    """
    svc = getattr(request.state, "web_service", None)
    if svc is not None:
        return svc
    return get_service()


