from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass

from publisher_v2.config.source import ConfigSource, RuntimeConfig
from publisher_v2.web.service import WebImageService


@dataclass
class _Entry:
    service: WebImageService
    expires_at: float
    config_version: str | None


class TenantServiceFactory:
    """
    Cache tenant-scoped WebImageService instances.

    - Keyed by tenant with config_version-aware invalidation
    - LRU eviction + TTL
    """

    def __init__(self, *, max_size: int = 1000, ttl_seconds: int = 600) -> None:
        self._max_size = max(1, int(max_size))
        self._ttl_seconds = max(1, int(ttl_seconds))
        self._data: "OrderedDict[str, _Entry]" = OrderedDict()

    def _effective_ttl(self, runtime: RuntimeConfig) -> int:
        if runtime.ttl_seconds is None:
            return self._ttl_seconds
        return min(self._ttl_seconds, int(runtime.ttl_seconds))

    async def get_service(self, source: ConfigSource, runtime: RuntimeConfig) -> WebImageService:
        tenant = runtime.tenant or "default"
        now = time.time()

        entry = self._data.get(tenant)
        if entry is not None:
            self._data.move_to_end(tenant)
            if entry.config_version == runtime.config_version and now <= entry.expires_at:
                return entry.service

        # Create new tenant-scoped service
        svc = WebImageService(runtime=runtime, config_source=source)
        expires = now + self._effective_ttl(runtime)
        self._data[tenant] = _Entry(service=svc, expires_at=expires, config_version=runtime.config_version)
        self._data.move_to_end(tenant)

        while len(self._data) > self._max_size:
            self._data.popitem(last=False)

        return svc


