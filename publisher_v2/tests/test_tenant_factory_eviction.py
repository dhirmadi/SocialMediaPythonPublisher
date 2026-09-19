"""REL-6 (#86): tenant eviction/replacement closes services and stops meters."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from publisher_v2.config.source import RuntimeConfig
from publisher_v2.web.tenant_factory import TenantServiceFactory


class _FakeService:
    def __init__(self, runtime=None, config_source=None) -> None:
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True


def _runtime(tenant: str, version: str = "v1", ttl: int | None = None) -> RuntimeConfig:
    return RuntimeConfig(
        host=f"{tenant}.example.test",
        tenant=tenant,
        config=SimpleNamespace(),  # type: ignore[arg-type]
        config_version=version,
        ttl_seconds=ttl,
    )


@pytest.fixture
def factory(monkeypatch: pytest.MonkeyPatch) -> TenantServiceFactory:
    monkeypatch.setattr("publisher_v2.web.tenant_factory.WebImageService", _FakeService)
    return TenantServiceFactory(max_size=2, ttl_seconds=600)


async def test_replacing_stale_version_closes_old_service(factory: TenantServiceFactory) -> None:
    old = await factory.get_service(None, _runtime("a", "v1"))  # type: ignore[arg-type]
    new = await factory.get_service(None, _runtime("a", "v2"))  # type: ignore[arg-type]
    assert new is not old
    assert old.closed is True
    assert new.closed is False


async def test_lru_eviction_closes_evicted_service(factory: TenantServiceFactory) -> None:
    a = await factory.get_service(None, _runtime("a"))  # type: ignore[arg-type]
    await factory.get_service(None, _runtime("b"))  # type: ignore[arg-type]
    await factory.get_service(None, _runtime("c"))  # type: ignore[arg-type]
    assert a.closed is True


async def test_no_service_growth_over_ttl_cycles(
    monkeypatch: pytest.MonkeyPatch, factory: TenantServiceFactory
) -> None:
    fake_now = {"t": 1000.0}
    monkeypatch.setattr("publisher_v2.web.tenant_factory.time.time", lambda: fake_now["t"])
    created: list[_FakeService] = []

    class _Tracking(_FakeService):
        def __init__(self, runtime=None, config_source=None) -> None:
            super().__init__(runtime, config_source)
            created.append(self)

    monkeypatch.setattr("publisher_v2.web.tenant_factory.WebImageService", _Tracking)
    for _ in range(3):
        await factory.get_service(None, _runtime("a", ttl=100))  # type: ignore[arg-type]
        fake_now["t"] += 101
    # Three TTL cycles → three services, and every superseded one is closed.
    assert len(created) == 3
    assert [s.closed for s in created] == [True, True, False]


async def test_shutdown_closes_all_cached_services(factory: TenantServiceFactory) -> None:
    a = await factory.get_service(None, _runtime("a"))  # type: ignore[arg-type]
    b = await factory.get_service(None, _runtime("b"))  # type: ignore[arg-type]
    await factory.shutdown()
    assert a.closed is True
    assert b.closed is True
