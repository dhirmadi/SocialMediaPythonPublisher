from __future__ import annotations

import json

import pytest
import httpx

from publisher_v2.config.orchestrator_client import OrchestratorClient
from publisher_v2.config.source import OrchestratorConfigSource


def _make_source(transport: httpx.MockTransport, monkeypatch: pytest.MonkeyPatch) -> OrchestratorConfigSource:
    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orch.test")
    monkeypatch.setenv("ORCHESTRATOR_SERVICE_TOKEN", "svc-token")
    monkeypatch.setenv("ORCHESTRATOR_BASE_DOMAIN", "shibari.photo")
    monkeypatch.setenv("DROPBOX_APP_KEY", "app_key")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "app_secret")
    monkeypatch.setenv("CREDENTIAL_CACHE_ENABLED", "true")
    monkeypatch.setenv("CREDENTIAL_CACHE_TTL_SECONDS", "600")

    src = OrchestratorConfigSource()
    client = httpx.AsyncClient(transport=transport, base_url="https://orch.test")
    orch = OrchestratorClient(base_url="https://orch.test", service_token="svc-token", prefer_post=True, client=client)

    # Speed tests by disabling sleep
    async def _no_sleep(_ms: int) -> None:
        return None

    orch._sleep = _no_sleep  # type: ignore[method-assign]
    src._client = orch  # type: ignore[attr-defined]
    return src


@pytest.mark.asyncio
async def test_resolve_each_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"resolve": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/credentials/resolve":
            calls["resolve"] += 1
            body = json.loads(request.content.decode("utf-8"))
            ref = body["credentials_ref"]
            if ref == "oa-ref":
                return httpx.Response(200, json={"provider": "openai", "version": "v1", "api_key": "sk-test-key-for-testing-purposes-only"})
            if ref == "tg-ref":
                return httpx.Response(200, json={"provider": "telegram", "version": "v1", "bot_token": "123:abc"})
            if ref == "smtp-ref":
                return httpx.Response(200, json={"provider": "smtp", "version": "v1", "password": "pw"})
            if ref == "db-ref":
                return httpx.Response(200, json={"provider": "dropbox", "version": "v1", "refresh_token": "rt", "expires_at": None})
        return httpx.Response(500)

    src = _make_source(httpx.MockTransport(handler), monkeypatch)

    r1 = await src.get_credentials("xxx.shibari.photo", "oa-ref")
    assert r1["provider"] == "openai"
    r2 = await src.get_credentials("xxx.shibari.photo", "tg-ref")
    assert r2["provider"] == "telegram"
    r3 = await src.get_credentials("xxx.shibari.photo", "smtp-ref")
    assert r3["provider"] == "smtp"
    r4 = await src.get_credentials("xxx.shibari.photo", "db-ref")
    assert r4["provider"] == "dropbox"
    assert calls["resolve"] == 4


@pytest.mark.asyncio
async def test_cache_hit_skips_network(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"resolve": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/credentials/resolve":
            calls["resolve"] += 1
            return httpx.Response(200, json={"provider": "openai", "version": "v1", "api_key": "sk-test-key-for-testing-purposes-only"})
        return httpx.Response(500)

    src = _make_source(httpx.MockTransport(handler), monkeypatch)
    _ = await src.get_credentials("xxx.shibari.photo", "oa-ref")
    _ = await src.get_credentials("xxx.shibari.photo", "oa-ref")
    assert calls["resolve"] == 1


