"""#131: voice matching defaults on through the real orchestrator config source.

The real ``OrchestratorConfigSource`` parses a runtime payload served over an
``httpx.MockTransport`` (the orchestrator HTTP API is the external boundary).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from publisher_v2.config.orchestrator_client import OrchestratorClient
from publisher_v2.config.source import OrchestratorConfigSource


def _source(features: dict[str, Any], content: dict[str, Any], monkeypatch: pytest.MonkeyPatch):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/runtime/by-host":
            return httpx.Response(
                200,
                json={
                    "schema_version": 2,
                    "tenant": "xxx",
                    "app_type": "publisher_v2",
                    "config_version": "v",
                    "ttl_seconds": 600,
                    "config": {
                        "features": features,
                        "storage": {
                            "provider": "dropbox",
                            "credentials_ref": "db-ref",
                            "paths": {"root": "/Photos/xxx"},
                        },
                        "publishers": [],
                        "content": content,
                    },
                },
            )
        if request.url.path == "/v1/credentials/resolve":
            assert json.loads(request.content)["credentials_ref"] == "db-ref"
            return httpx.Response(200, json={"provider": "dropbox", "version": "v1", "refresh_token": "rt"})
        return httpx.Response(500, json={"error": "unexpected"})

    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orch.test")
    monkeypatch.setenv("ORCHESTRATOR_SERVICE_TOKEN", "svc-token")
    monkeypatch.setenv("ORCHESTRATOR_BASE_DOMAIN", "shibari.photo")
    monkeypatch.setenv("DROPBOX_APP_KEY", "app_key")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "app_secret")
    src = OrchestratorConfigSource()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://orch.test")
    src._client = OrchestratorClient(  # type: ignore[attr-defined]
        base_url="https://orch.test", service_token="svc-token", prefer_post=True, client=client
    )
    return src


_BASE_FEATURES = {"publish_enabled": True, "analyze_caption_enabled": True}
_PROFILE = {"voice_profile": ["a caption I would have written"]}


async def test_profile_without_voice_key_enables_voice_matching(monkeypatch: pytest.MonkeyPatch) -> None:
    rc = await _source(dict(_BASE_FEATURES), _PROFILE, monkeypatch).get_config("xxx.shibari.photo")
    assert rc.config.content.voice_profile == ["a caption I would have written"]
    assert rc.config.features.voice_matching_enabled is True


async def test_profile_with_null_voice_flag_enables_voice_matching(monkeypatch: pytest.MonkeyPatch) -> None:
    """The real orchestrator projection (platform-orchestrator, Publisher #131) sends unset as null."""
    features = {**_BASE_FEATURES, "voice_matching_enabled": None}
    rc = await _source(features, _PROFILE, monkeypatch).get_config("xxx.shibari.photo")
    assert rc.config.features.voice_matching_enabled is True


async def test_null_voice_flag_without_profile_stays_off(monkeypatch: pytest.MonkeyPatch) -> None:
    features = {**_BASE_FEATURES, "voice_matching_enabled": None}
    rc = await _source(features, {}, monkeypatch).get_config("xxx.shibari.photo")
    assert rc.config.features.voice_matching_enabled is False


async def test_profile_with_explicit_false_keeps_voice_matching_off(monkeypatch: pytest.MonkeyPatch) -> None:
    features = {**_BASE_FEATURES, "voice_matching_enabled": False}
    rc = await _source(features, _PROFILE, monkeypatch).get_config("xxx.shibari.photo")
    assert rc.config.features.voice_matching_enabled is False


async def test_explicit_true_without_profile_is_honoured(monkeypatch: pytest.MonkeyPatch) -> None:
    features = {**_BASE_FEATURES, "voice_matching_enabled": True}
    rc = await _source(features, {}, monkeypatch).get_config("xxx.shibari.photo")
    assert rc.config.features.voice_matching_enabled is True


async def test_other_orchestrator_feature_defaults_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only voice matching becomes profile-derived: absent flags keep the orchestrator model defaults."""
    rc = await _source({}, _PROFILE, monkeypatch).get_config("xxx.shibari.photo")
    assert rc.config.features.publish_enabled is False
    assert rc.config.features.analyze_caption_enabled is False
