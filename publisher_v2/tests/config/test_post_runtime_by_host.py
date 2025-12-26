from __future__ import annotations

import pytest
import httpx

from publisher_v2.config.orchestrator_client import OrchestratorClient


@pytest.mark.asyncio
async def test_post_preferred_and_405_fallback_cached() -> None:
    calls = {"post": 0, "get": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/runtime/by-host" and request.method == "POST":
            calls["post"] += 1
            return httpx.Response(405, json={"detail": "Method Not Allowed"})
        if request.url.path == "/v1/runtime/by-host" and request.method == "GET":
            calls["get"] += 1
            return httpx.Response(
                200,
                json={
                    "schema_version": 1,
                    "tenant": "xxx",
                    "app_type": "publisher_v2",
                    "config_version": "cv1",
                    "ttl_seconds": 600,
                    "config": {"features": {"publish_enabled": False}, "storage": {"provider": "dropbox", "credentials_ref": "ref", "paths": {"root": "/Photos"}}},
                },
            )
        return httpx.Response(500, json={"error": "unexpected"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://orch.test") as client:
        orch = OrchestratorClient(base_url="https://orch.test", service_token="t", prefer_post=True, client=client)

        _ = await orch.get_runtime_by_host("xxx.shibari.photo")
        # Second call should not attempt POST again (cached unsupported)
        _ = await orch.get_runtime_by_host("xxx.shibari.photo")

    assert calls["post"] == 1
    assert calls["get"] == 2


@pytest.mark.asyncio
async def test_prefer_post_false_uses_get() -> None:
    calls = {"post": 0, "get": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/runtime/by-host" and request.method == "POST":
            calls["post"] += 1
            return httpx.Response(500)
        if request.url.path == "/v1/runtime/by-host" and request.method == "GET":
            calls["get"] += 1
            return httpx.Response(
                200,
                json={
                    "schema_version": 1,
                    "tenant": "xxx",
                    "app_type": "publisher_v2",
                    "config_version": "cv1",
                    "ttl_seconds": 600,
                    "config": {"features": {"publish_enabled": False}, "storage": {"provider": "dropbox", "credentials_ref": "ref", "paths": {"root": "/Photos"}}},
                },
            )
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://orch.test") as client:
        orch = OrchestratorClient(base_url="https://orch.test", service_token="t", prefer_post=False, client=client)
        _ = await orch.get_runtime_by_host("xxx.shibari.photo")

    assert calls["post"] == 0
    assert calls["get"] == 1


