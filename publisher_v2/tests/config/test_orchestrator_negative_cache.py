"""Negative caching of unknown hosts in OrchestratorConfigSource.get_config.

Incident 2026-09-27: a bot scan of custom domains bound to the Heroku app but without an
orchestrator tenant turned every request into a ``POST /v1/runtime/by-host`` (and a Postgres
query on the orchestrator), exhausting the orchestrator's DB connections. Unknown hosts (404)
and hosts not bound to publisher_v2 are now remembered per normalized host for a short TTL
(60s) in a bounded LRU, so repeat lookups never reach the orchestrator while the entry is fresh.

Only the orchestrator HTTP boundary is mocked (``httpx.MockTransport``); the clock is advanced
by patching ``time.time`` (the clock ``RuntimeConfigCache`` uses).
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

import publisher_v2.config.source as source_module
from publisher_v2.config.orchestrator_client import OrchestratorClient
from publisher_v2.config.source import OrchestratorConfigSource
from publisher_v2.core.exceptions import (
    OrchestratorUnavailableError,
    TenantNotFoundError,
    UnsupportedSchemaError,
)

Handler = Callable[[httpx.Request], Awaitable[httpx.Response]]

NEGATIVE_TTL_SECONDS = 60  # decided behaviour: 60s negative TTL


class _Clock:
    """Controllable replacement for ``time.time``."""

    def __init__(self, start: float = 1_800_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> _Clock:
    c = _Clock()
    monkeypatch.setattr(time, "time", c)
    return c


def _make_source(handler: Handler, monkeypatch: pytest.MonkeyPatch) -> OrchestratorConfigSource:
    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orch.test")
    monkeypatch.setenv("ORCHESTRATOR_SERVICE_TOKEN", "svc-token")
    monkeypatch.setenv("ORCHESTRATOR_BASE_DOMAIN", "shibari.photo")
    monkeypatch.setenv("DROPBOX_APP_KEY", "app_key")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "app_secret")
    monkeypatch.setenv("ORCHESTRATOR_PREFER_POST", "true")

    src = OrchestratorConfigSource()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://orch.test")
    orch = OrchestratorClient(base_url="https://orch.test", service_token="svc-token", prefer_post=True, client=client)

    async def _no_sleep(delay_ms: int) -> None:
        return None

    # Retry backoff on 5xx must not slow the suite down.
    orch._sleep = _no_sleep  # type: ignore[method-assign]
    src._client = orch  # type: ignore[attr-defined]
    return src


def _valid_runtime_payload(tenant: str = "newtenant") -> dict[str, Any]:
    return {
        "schema_version": 2,
        "tenant": tenant,
        "app_type": "publisher_v2",
        "config_version": "cfgv2",
        "ttl_seconds": 600,
        "config": {
            "features": {
                "publish_enabled": False,
                "analyze_caption_enabled": True,
                "keep_enabled": True,
                "remove_enabled": True,
                "auto_view_enabled": False,
            },
            "storage": {
                "provider": "dropbox",
                "credentials_ref": "db-ref",
                "paths": {"root": f"/Photos/{tenant}"},
            },
            "publishers": [],
            "ai": {"credentials_ref": "oa-ref", "vision_model": "gpt-4o", "caption_model": "gpt-4o-mini"},
            "content": {"archive": True, "debug": False, "hashtag_string": "#x"},
        },
    }


class _Recorder:
    """Counts runtime lookups per host and answers according to a mutable mode."""

    def __init__(self, mode: str = "404") -> None:
        self.mode = mode
        self.runtime_calls: list[str] = []

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/runtime/by-host":
            body = json.loads(request.content.decode("utf-8")) if request.content else {}
            self.runtime_calls.append(str(body.get("host") or request.url.params.get("host")))
            if self.mode == "404":
                return httpx.Response(404, json={"error": "not found"})
            if self.mode == "503":
                return httpx.Response(503, json={"error": "unavailable"})
            if self.mode == "unbound":
                payload = _valid_runtime_payload("othertenant")
                payload["app_type"] = "some_other_app"
                return httpx.Response(200, json=payload)
            if self.mode == "schema_v1":
                payload = _valid_runtime_payload()
                payload["schema_version"] = 1
                return httpx.Response(200, json=payload)
            if self.mode == "ok":
                return httpx.Response(200, json=_valid_runtime_payload())
        if request.url.path == "/v1/credentials/resolve":
            return httpx.Response(
                200, json={"provider": "dropbox", "version": "v1", "refresh_token": "rt", "expires_at": None}
            )
        return httpx.Response(500, json={"error": "unexpected"})


@pytest.mark.asyncio
async def test_unknown_host_is_negatively_cached_and_skips_the_orchestrator(
    monkeypatch: pytest.MonkeyPatch, clock: _Clock
) -> None:
    rec = _Recorder("404")
    src = _make_source(rec, monkeypatch)

    with pytest.raises(TenantNotFoundError):
        await src.get_config("archive.shibari.photo")
    assert len(rec.runtime_calls) == 1

    # Within the TTL, and via a host that normalizes to the same key: no orchestrator call.
    clock.advance(NEGATIVE_TTL_SECONDS - 1)
    with pytest.raises(TenantNotFoundError):
        await src.get_config("ARCHIVE.shibari.photo")
    with pytest.raises(TenantNotFoundError):
        await src.get_config("archive.shibari.photo")

    assert len(rec.runtime_calls) == 1, f"expected one orchestrator lookup, got {rec.runtime_calls}"


@pytest.mark.asyncio
async def test_negative_cache_expires_so_a_new_tenant_is_picked_up(
    monkeypatch: pytest.MonkeyPatch, clock: _Clock
) -> None:
    rec = _Recorder("404")
    src = _make_source(rec, monkeypatch)

    with pytest.raises(TenantNotFoundError):
        await src.get_config("tinyhouse.shibari.photo")
    with pytest.raises(TenantNotFoundError):
        await src.get_config("tinyhouse.shibari.photo")
    assert len(rec.runtime_calls) == 1, "second lookup within the TTL must be served from the negative cache"

    # Tenant gets provisioned; once the negative TTL has lapsed the orchestrator is asked again.
    rec.mode = "ok"
    clock.advance(NEGATIVE_TTL_SECONDS + 1)

    rc = await src.get_config("tinyhouse.shibari.photo")

    assert len(rec.runtime_calls) == 2
    assert rc.tenant == "newtenant"


@pytest.mark.asyncio
async def test_unbound_app_type_is_negatively_cached(monkeypatch: pytest.MonkeyPatch, clock: _Clock) -> None:
    rec = _Recorder("unbound")
    src = _make_source(rec, monkeypatch)

    with pytest.raises(TenantNotFoundError, match="not bound to publisher_v2"):
        await src.get_config("other.shibari.photo")
    with pytest.raises(TenantNotFoundError):
        await src.get_config("other.shibari.photo")

    assert len(rec.runtime_calls) == 1, f"expected one orchestrator lookup, got {rec.runtime_calls}"


@pytest.mark.asyncio
async def test_orchestrator_unavailable_is_not_negatively_cached(
    monkeypatch: pytest.MonkeyPatch, clock: _Clock
) -> None:
    rec = _Recorder("503")
    src = _make_source(rec, monkeypatch)

    with pytest.raises(OrchestratorUnavailableError):
        await src.get_config("flaky.shibari.photo")
    first_attempts = len(rec.runtime_calls)
    assert first_attempts >= 1

    with pytest.raises(OrchestratorUnavailableError):
        await src.get_config("flaky.shibari.photo")
    assert len(rec.runtime_calls) > first_attempts, "a transient outage must not be negatively cached"

    # And once the orchestrator recovers, the host resolves immediately (no stale 'unknown' entry).
    rec.mode = "ok"
    rc = await src.get_config("flaky.shibari.photo")
    assert rc.tenant == "newtenant"


@pytest.mark.asyncio
async def test_unsupported_schema_is_not_negatively_cached(monkeypatch: pytest.MonkeyPatch, clock: _Clock) -> None:
    rec = _Recorder("schema_v1")
    src = _make_source(rec, monkeypatch)

    with pytest.raises(UnsupportedSchemaError):
        await src.get_config("old.shibari.photo")
    with pytest.raises(UnsupportedSchemaError):
        await src.get_config("old.shibari.photo")

    assert len(rec.runtime_calls) == 2


@pytest.mark.asyncio
async def test_negative_cache_is_bounded(monkeypatch: pytest.MonkeyPatch, clock: _Clock) -> None:
    max_size = 3
    # The bound is a module constant read when the source is constructed.
    monkeypatch.setattr(source_module, "NEGATIVE_CACHE_MAX_SIZE", max_size, raising=False)
    rec = _Recorder("404")
    src = _make_source(rec, monkeypatch)

    hosts = [f"bot{i}.shibari.photo" for i in range(max_size + 2)]
    for h in hosts:
        with pytest.raises(TenantNotFoundError):
            await src.get_config(h)
    assert len(rec.runtime_calls) == len(hosts)

    # The most recent `max_size` hosts are still negatively cached ...
    for h in hosts[-max_size:]:
        with pytest.raises(TenantNotFoundError):
            await src.get_config(h)
    assert len(rec.runtime_calls) == len(hosts), "most recent unknown hosts must still be cached"

    # ... while the oldest ones were evicted (LRU) and go back to the orchestrator.
    with pytest.raises(TenantNotFoundError):
        await src.get_config(hosts[0])
    assert len(rec.runtime_calls) == len(hosts) + 1, "oldest unknown host must have been evicted"

    negative_cache = src._negative_cache  # type: ignore[attr-defined]
    assert len(negative_cache._data) <= max_size


@pytest.mark.asyncio
async def test_healthcheck_still_reaches_the_orchestrator(monkeypatch: pytest.MonkeyPatch, clock: _Clock) -> None:
    rec = _Recorder("404")
    src = _make_source(rec, monkeypatch)
    hc_host = src.check_connectivity_host()

    # Even if the synthetic healthcheck host lands in the negative cache via get_config ...
    with pytest.raises(TenantNotFoundError):
        await src.get_config(hc_host)
    assert len(rec.runtime_calls) == 1

    # ... every readiness probe must still round-trip to the orchestrator (404 == reachable).
    await src.check_connectivity()
    await src.check_connectivity()
    assert rec.runtime_calls == [hc_host, hc_host, hc_host]

    # And an unreachable orchestrator must still fail the probe.
    rec.mode = "503"
    with pytest.raises(OrchestratorUnavailableError):
        await src.check_connectivity()
