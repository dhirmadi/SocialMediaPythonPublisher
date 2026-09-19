"""REL-6 (#86): tenant eviction/replacement closes services and stops meters."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from publisher_v2.config.source import RuntimeConfig
from publisher_v2.web.tenant_factory import TenantServiceFactory


class _FakeService:
    # #143: the factory now forwards the already-parsed settings to the service.
    def __init__(self, runtime=None, config_source=None, settings=None) -> None:
        self.settings = settings
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
        def __init__(self, runtime=None, config_source=None, settings=None) -> None:
            super().__init__(runtime, config_source, settings)
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


class TestProcessFactorySingleton:
    """#143 review: the middleware path and the lifespan shutdown must share one factory.

    With ``lru_cache`` keyed on the sizing arguments, ``_tenant_service_factory()``
    (shutdown, defaults) and ``_tenant_service_factory(max, ttl)`` (middleware,
    settings) were different cache keys: shutdown closed an empty factory while
    the live one was evicted without ``aclose()`` ever running (#86 regression).
    """

    @staticmethod
    async def _run_middleware(monkeypatch: pytest.MonkeyPatch, app) -> None:
        from starlette.requests import Request

        from publisher_v2.web import middleware as mw

        class _Source:
            async def get_config(self, host: str) -> RuntimeConfig:
                return _runtime("t1")

        monkeypatch.setattr(mw, "get_config_source", lambda: _Source())
        monkeypatch.setattr("publisher_v2.web.tenant_factory.WebImageService", _FakeService)

        request = Request(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/images",
                "headers": [(b"host", b"t1.example.test")],
                "query_string": b"",
                "app": app,
            }
        )

        async def _call_next(_req):
            return "ok"

        await mw.tenant_middleware(request, _call_next)

    async def test_middleware_and_shutdown_share_one_instance(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from publisher_v2.web import middleware as mw

        mw.reset_tenant_service_factory()
        try:
            app = SimpleNamespace(state=SimpleNamespace(runtime_settings=_orchestrator_settings()))
            await self._run_middleware(monkeypatch, app)
            live = mw._existing_tenant_service_factory()
            assert live is not None
            assert list(live._data) == ["t1"]
        finally:
            mw.reset_tenant_service_factory()

    async def test_existing_factory_is_none_before_any_request(self) -> None:
        from publisher_v2.web import middleware as mw

        mw.reset_tenant_service_factory()
        assert mw._existing_tenant_service_factory() is None

    async def test_lifespan_shutdown_closes_middleware_registered_services(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from publisher_v2.web import middleware as mw
        from publisher_v2.web.app import app as real_app
        from publisher_v2.web.app import lifespan

        monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orchestrator.example")
        monkeypatch.setenv("CONFIG_SOURCE", "orchestrator")
        mw.reset_tenant_service_factory()
        try:
            async with lifespan(real_app):
                await self._run_middleware(monkeypatch, real_app)
                factory = mw._existing_tenant_service_factory()
                assert factory is not None
                service = factory._data["t1"].service
                assert service.closed is False
            assert service.closed is True, "lifespan shutdown did not close the live tenant services"
        finally:
            mw.reset_tenant_service_factory()


def _orchestrator_settings():
    from publisher_v2.config.runtime_settings import RuntimeSettings

    return RuntimeSettings(config_source="orchestrator", orchestrator_base_url="https://orchestrator.example")
