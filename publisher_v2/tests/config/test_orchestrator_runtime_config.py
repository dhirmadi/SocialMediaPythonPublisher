from __future__ import annotations

import json

import pytest
import httpx

from publisher_v2.config.orchestrator_client import OrchestratorClient
from publisher_v2.config.source import OrchestratorConfigSource
from publisher_v2.core.exceptions import TenantNotFoundError


def _make_source(transport: httpx.MockTransport, monkeypatch: pytest.MonkeyPatch) -> OrchestratorConfigSource:
    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orch.test")
    monkeypatch.setenv("ORCHESTRATOR_SERVICE_TOKEN", "svc-token")
    monkeypatch.setenv("ORCHESTRATOR_BASE_DOMAIN", "shibari.photo")
    monkeypatch.setenv("DROPBOX_APP_KEY", "app_key")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "app_secret")
    # Prefer POST by default
    monkeypatch.setenv("ORCHESTRATOR_PREFER_POST", "true")

    src = OrchestratorConfigSource()
    # Inject test httpx client
    client = httpx.AsyncClient(transport=transport, base_url="https://orch.test")
    src._client = OrchestratorClient(base_url="https://orch.test", service_token="svc-token", prefer_post=True, client=client)  # type: ignore[attr-defined]
    return src


@pytest.mark.asyncio
async def test_parses_schema_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"runtime": 0, "resolve": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/runtime/by-host" and request.method == "POST":
            calls["runtime"] += 1
            body = json.loads(request.content.decode("utf-8"))
            assert body["host"] == "xxx.shibari.photo"
            return httpx.Response(
                200,
                json={
                    "schema_version": 2,
                    "tenant": "xxx",
                    "app_type": "publisher_v2",
                    "config_version": "cfgv2",
                    "ttl_seconds": 600,
                    "config": {
                        "features": {"publish_enabled": True, "analyze_caption_enabled": True, "keep_enabled": True, "remove_enabled": True, "auto_view_enabled": False},
                        "storage": {"provider": "dropbox", "credentials_ref": "db-ref", "paths": {"root": "/Photos/xxx/2025"}},
                        "publishers": [
                            {"id": "tg1", "type": "telegram", "enabled": True, "credentials_ref": "tg-ref", "config": {"channel_id": "@chan"}},
                            {"id": "fl1", "type": "fetlife", "enabled": True, "credentials_ref": None, "config": {"recipient": "123@upload.fetlife.com", "caption_target": "subject", "subject_mode": "normal"}},
                        ],
                        "email_server": {"host": "smtp.test", "port": 587, "use_tls": True, "from_email": "bot@test.com", "username": None, "password_ref": "smtp-ref"},
                        "ai": {"credentials_ref": "oa-ref", "vision_model": "gpt-4o", "caption_model": "gpt-4o-mini"},
                        "content": {"archive": True, "debug": False, "hashtag_string": "#x"},
                    },
                },
            )
        if request.url.path == "/v1/credentials/resolve" and request.method == "POST":
            calls["resolve"] += 1
            assert request.headers.get("X-Tenant") == "xxx"
            body = json.loads(request.content.decode("utf-8"))
            assert body["credentials_ref"] == "db-ref"
            return httpx.Response(200, json={"provider": "dropbox", "version": "v1", "refresh_token": "rt", "expires_at": None})
        return httpx.Response(500, json={"error": "unexpected"})

    transport = httpx.MockTransport(handler)
    src = _make_source(transport, monkeypatch)

    rc = await src.get_config("xxx.shibari.photo")
    assert rc.tenant == "xxx"
    assert rc.schema_version == 2
    assert rc.config.dropbox.image_folder == "/Photos/xxx/2025"
    assert rc.config.platforms.telegram_enabled is True
    assert rc.config.platforms.email_enabled is True
    assert rc.config.features.analyze_caption_enabled is True
    assert rc.credentials_refs is not None
    assert rc.credentials_refs["storage"] == "db-ref"
    assert rc.credentials_refs["openai"] == "oa-ref"
    assert calls["runtime"] == 1
    assert calls["resolve"] == 1


@pytest.mark.asyncio
async def test_schema_v1_fallback_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/runtime/by-host" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "schema_version": 1,
                    "tenant": "xxx",
                    "app_type": "publisher_v2",
                    "config_version": "cfgv1",
                    "ttl_seconds": 600,
                    "config": {
                        "features": {"publish_enabled": True, "analyze_caption_enabled": True},
                        "storage": {"provider": "dropbox", "credentials_ref": "db-ref", "paths": {"root": "/Photos/xxx"}},
                    },
                },
            )
        if request.url.path == "/v1/credentials/resolve" and request.method == "POST":
            return httpx.Response(200, json={"provider": "dropbox", "version": "v1", "refresh_token": "rt", "expires_at": None})
        return httpx.Response(500)

    src = _make_source(httpx.MockTransport(handler), monkeypatch)
    rc = await src.get_config("xxx.shibari.photo")
    # v1 fallback forces AI disabled, no publishers
    assert rc.config.features.analyze_caption_enabled is False
    assert rc.config.platforms.telegram_enabled is False
    assert rc.config.platforms.email_enabled is False


@pytest.mark.asyncio
async def test_tenant_not_found_on_404(monkeypatch: pytest.MonkeyPatch) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/runtime/by-host":
            return httpx.Response(404, json={"error": "not found"})
        return httpx.Response(500)

    src = _make_source(httpx.MockTransport(handler), monkeypatch)
    with pytest.raises(TenantNotFoundError):
        await src.get_config("xxx.shibari.photo")


