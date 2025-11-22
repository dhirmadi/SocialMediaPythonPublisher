from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.requests import Request

from publisher_v2.web.app import app, _startup, _get_correlation_id, get_service


class _StubWebService:
    def __init__(self) -> None:
        self.random_error: Exception | None = None
        self.analyze_error: Exception | None = None
        self.publish_error: Exception | None = None
        self.keep_error: Exception | None = None
        self.remove_error: Exception | None = None
        features = SimpleNamespace(
            analyze_caption_enabled=True,
            publish_enabled=True,
            keep_enabled=True,
            remove_enabled=True,
            auto_view_enabled=False,
        )
        platforms = SimpleNamespace(telegram_enabled=False, instagram_enabled=False, email_enabled=False)
        self.config = SimpleNamespace(
            features=features,
            platforms=platforms,
            telegram=None,
            instagram=None,
            email=None,
        )

    async def get_random_image(self):
        if self.random_error:
            raise self.random_error
        return SimpleNamespace(
            filename="one.jpg",
            temp_url="https://temp",
            sha256=None,
            caption=None,
            sd_caption=None,
            metadata=None,
            has_sidecar=False,
        )

    async def analyze_and_caption(self, filename: str, *, correlation_id: str, force_refresh: bool):
        if self.analyze_error:
            raise self.analyze_error
        return SimpleNamespace(
            filename=filename,
            description="desc",
            mood="calm",
            tags=["a"],
            nsfw=False,
            caption="c",
            sd_caption=None,
            sidecar_written=False,
        )

    async def publish_image(self, filename: str, platforms: list[str] | None):
        if self.publish_error:
            raise self.publish_error
        return SimpleNamespace(filename=filename, results={}, archived=False, any_success=False)

    async def keep_image(self, filename: str):
        if self.keep_error:
            raise self.keep_error
        return SimpleNamespace(filename=filename, action="keep", destination_folder="keep", preview_only=False)

    async def remove_image(self, filename: str):
        if self.remove_error:
            raise self.remove_error
        return SimpleNamespace(filename=filename, action="remove", destination_folder="remove", preview_only=False)


@pytest.fixture
def client_factory():
    clients: list[TestClient] = []

    def _make(service: _StubWebService) -> TestClient:
        app.dependency_overrides[get_service] = lambda: service
        client = TestClient(app)
        clients.append(client)
        return client

    yield _make

    for client in clients:
        client.close()
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_startup_and_correlation_id(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WEB_DEBUG", "1")
    await _startup()

    scope = {"type": "http", "headers": [(b"x-request-id", b"abc")]}
    req = Request(scope)
    assert _get_correlation_id(req) == "abc"


def test_admin_login_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("web_admin_pw", raising=False)
    with TestClient(app) as client:
        resp = client.post("/api/admin/login", json={"password": "pw"})
        assert resp.status_code == 503


def test_admin_login_empty_password(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("web_admin_pw", "secret")
    with TestClient(app) as client:
        resp = client.post("/api/admin/login", json={"password": ""})
        assert resp.status_code == 401


def test_random_image_requires_admin_when_unconfigured(client_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _StubWebService()
    monkeypatch.setattr("publisher_v2.web.app.is_admin_configured", lambda: False)
    client = client_factory(service)
    resp = client.get("/api/images/random")
    assert resp.status_code == 503


def test_random_image_requires_admin_cookie(client_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _StubWebService()
    monkeypatch.setattr("publisher_v2.web.app.is_admin_configured", lambda: True)

    def _require_admin(_request):
        raise HTTPException(status_code=403, detail="no admin")

    monkeypatch.setattr("publisher_v2.web.app.require_admin", _require_admin)
    client = client_factory(service)
    resp = client.get("/api/images/random")
    assert resp.status_code == 403


def test_random_image_not_found_and_error(client_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _StubWebService()
    service.config.features.auto_view_enabled = True
    monkeypatch.setattr("publisher_v2.web.app.is_admin_configured", lambda: False)

    client = client_factory(service)
    service.random_error = FileNotFoundError()
    resp = client.get("/api/images/random")
    assert resp.status_code == 404

    service.random_error = RuntimeError("boom")
    resp2 = client.get("/api/images/random")
    assert resp2.status_code == 500


def test_analyze_image_error_paths(client_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _StubWebService()

    async def _async_noop(_request):
        return None

    def _sync_noop(_request):
        return None

    monkeypatch.setattr("publisher_v2.web.app.require_auth", _async_noop)
    monkeypatch.setattr("publisher_v2.web.app.require_admin", _sync_noop)
    client = client_factory(service)
    service.analyze_error = RuntimeError("image not found in service")
    resp = client.post("/api/images/sample/analyze")
    assert resp.status_code == 404

    service.analyze_error = RuntimeError("boom")
    resp2 = client.post("/api/images/sample/analyze")
    assert resp2.status_code == 500


def test_publish_image_success_and_errors(client_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _StubWebService()

    async def _async_noop(_request):
        return None

    def _sync_noop(_request):
        return None

    monkeypatch.setattr("publisher_v2.web.app.require_auth", _async_noop)
    monkeypatch.setattr("publisher_v2.web.app.require_admin", _sync_noop)
    client = client_factory(service)
    resp = client.post("/api/images/sample/publish", json={"platforms": ["telegram"]})
    assert resp.status_code == 200
    assert resp.json()["any_success"] is False

    service.publish_error = PermissionError("nope")
    resp_forbidden = client.post("/api/images/sample/publish")
    assert resp_forbidden.status_code == 403

    service.publish_error = RuntimeError("fail")
    resp_error = client.post("/api/images/sample/publish")
    assert resp_error.status_code == 500


def test_keep_and_remove_errors(client_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    service = _StubWebService()

    async def _async_noop(_request):
        return None

    def _sync_noop(_request):
        return None

    monkeypatch.setattr("publisher_v2.web.app.require_auth", _async_noop)
    monkeypatch.setattr("publisher_v2.web.app.require_admin", _sync_noop)
    client = client_factory(service)
    service.keep_error = RuntimeError("fail")
    keep_resp = client.post("/api/images/sample/keep")
    assert keep_resp.status_code == 500

    service.remove_error = RuntimeError("fail")
    remove_resp = client.post("/api/images/sample/remove")
    assert remove_resp.status_code == 500


def test_publishers_config_endpoint(client_factory) -> None:
    service = _StubWebService()
    service.config.platforms.telegram_enabled = True
    client = client_factory(service)
    resp = client.get("/api/config/publishers")
    assert resp.status_code == 200
    body = resp.json()
    assert body["telegram"] is False  # telegram config missing => False


