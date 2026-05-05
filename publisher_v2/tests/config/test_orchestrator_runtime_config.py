from __future__ import annotations

import json

import httpx
import pytest

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
    src._client = OrchestratorClient(
        base_url="https://orch.test", service_token="svc-token", prefer_post=True, client=client
    )  # type: ignore[attr-defined]
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
                        "features": {
                            "publish_enabled": True,
                            "analyze_caption_enabled": True,
                            "keep_enabled": True,
                            "remove_enabled": True,
                            "auto_view_enabled": False,
                        },
                        "storage": {
                            "provider": "dropbox",
                            "credentials_ref": "db-ref",
                            "paths": {"root": "/Photos/xxx/2025"},
                        },
                        "publishers": [
                            {
                                "id": "tg1",
                                "type": "telegram",
                                "enabled": True,
                                "credentials_ref": "tg-ref",
                                "config": {"channel_id": "@chan"},
                            },
                            {
                                "id": "fl1",
                                "type": "fetlife",
                                "enabled": True,
                                "credentials_ref": None,
                                "config": {
                                    "recipient": "123@upload.fetlife.com",
                                    "caption_target": "subject",
                                    "subject_mode": "normal",
                                },
                            },
                        ],
                        "email_server": {
                            "host": "smtp.test",
                            "port": 587,
                            "use_tls": True,
                            "from_email": "bot@test.com",
                            "username": None,
                            "password_ref": "smtp-ref",
                        },
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
            return httpx.Response(
                200, json={"provider": "dropbox", "version": "v1", "refresh_token": "rt", "expires_at": None}
            )
        return httpx.Response(500, json={"error": "unexpected"})

    transport = httpx.MockTransport(handler)
    src = _make_source(transport, monkeypatch)

    rc = await src.get_config("xxx.shibari.photo")
    assert rc.tenant == "xxx"
    assert rc.schema_version == 2
    assert rc.config.dropbox is not None
    assert rc.config.dropbox.image_folder == "/Photos/xxx/2025"
    assert rc.config.platforms.telegram_enabled is True
    assert rc.config.platforms.email_enabled is True
    assert rc.config.features.analyze_caption_enabled is True
    assert rc.credentials_refs is not None
    assert rc.credentials_refs["storage"] == "db-ref"
    assert rc.credentials_refs["openai"] == "oa-ref"
    assert rc.credentials_refs["smtp"] == "smtp-ref"
    assert calls["runtime"] == 1
    assert calls["resolve"] == 1


def _email_publisher_runtime_payload(
    *,
    publisher_type: str,
    recipient: str = "123@upload.fetlife.com",
    include_email_server: bool = True,
    from_email: str = "bot@test.com",
    password_ref: str | None = "smtp-ref",  # noqa: S107  test fixture, opaque ref not a real secret
) -> dict:
    config: dict = {
        "features": {
            "publish_enabled": True,
            "analyze_caption_enabled": True,
            "keep_enabled": True,
            "remove_enabled": True,
            "auto_view_enabled": False,
        },
        "storage": {
            "provider": "dropbox",
            "credentials_ref": "db-ref",
            "paths": {"root": "/Photos/xxx/2025"},
        },
        "publishers": [
            {
                "id": "em1",
                "type": publisher_type,
                "enabled": True,
                "credentials_ref": None,
                "config": {
                    "recipient": recipient,
                    "caption_target": "subject",
                    "subject_mode": "normal",
                },
            },
        ],
        "ai": {"credentials_ref": "oa-ref", "vision_model": "gpt-4o", "caption_model": "gpt-4o-mini"},
        "content": {"archive": True, "debug": False, "hashtag_string": "#x"},
    }
    if include_email_server:
        config["email_server"] = {
            "host": "smtp.test",
            "port": 587,
            "use_tls": True,
            "from_email": from_email,
            "username": None,
            "password_ref": password_ref,
        }
    return {
        "schema_version": 2,
        "tenant": "xxx",
        "app_type": "publisher_v2",
        "config_version": "cfgv2",
        "ttl_seconds": 600,
        "config": config,
    }


def _email_handler(payload: dict):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/v1/runtime/by-host" and request.method == "POST":
            return httpx.Response(200, json=payload)
        if request.url.path == "/v1/credentials/resolve" and request.method == "POST":
            return httpx.Response(
                200, json={"provider": "dropbox", "version": "v1", "refresh_token": "rt", "expires_at": None}
            )
        return httpx.Response(500, json={"error": "unexpected"})

    return handler


@pytest.mark.asyncio
async def test_publisher_type_email_enables_email_with_smtp_ref(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC1: publisher type 'email' parses identically to 'fetlife'."""
    payload = _email_publisher_runtime_payload(publisher_type="email")
    src = _make_source(httpx.MockTransport(_email_handler(payload)), monkeypatch)

    rc = await src.get_config("xxx.shibari.photo")

    assert rc.config.platforms.email_enabled is True
    assert rc.config.email is not None
    assert rc.config.email.recipient == "123@upload.fetlife.com"
    assert rc.config.email.sender == "bot@test.com"
    assert rc.config.email.smtp_server == "smtp.test"
    assert rc.config.email.smtp_port == 587
    assert rc.config.email.caption_target == "subject"
    assert rc.config.email.subject_mode == "normal"
    assert rc.credentials_refs is not None
    assert rc.credentials_refs.get("smtp") == "smtp-ref"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "kwargs",
    [
        {"recipient": ""},
        {"from_email": ""},
        {"password_ref": None},
    ],
)
async def test_publisher_type_email_disabled_when_required_field_missing(
    monkeypatch: pytest.MonkeyPatch, kwargs: dict
) -> None:
    """AC3: missing recipient / from_email / password_ref => email disabled, no smtp ref."""
    payload = _email_publisher_runtime_payload(publisher_type="email", **kwargs)
    src = _make_source(httpx.MockTransport(_email_handler(payload)), monkeypatch)

    rc = await src.get_config("xxx.shibari.photo")

    assert rc.config.platforms.email_enabled is False
    assert rc.config.email is None
    assert rc.credentials_refs is not None
    assert "smtp" not in rc.credentials_refs


@pytest.mark.asyncio
async def test_publisher_type_email_disabled_when_email_server_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC4: email_server absent => email_enabled False, no crash."""
    payload = _email_publisher_runtime_payload(publisher_type="email", include_email_server=False)
    src = _make_source(httpx.MockTransport(_email_handler(payload)), monkeypatch)

    rc = await src.get_config("xxx.shibari.photo")

    assert rc.config.platforms.email_enabled is False
    assert rc.config.email is None
    assert rc.credentials_refs is not None
    assert "smtp" not in rc.credentials_refs


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
                        "storage": {
                            "provider": "dropbox",
                            "credentials_ref": "db-ref",
                            "paths": {"root": "/Photos/xxx"},
                        },
                    },
                },
            )
        if request.url.path == "/v1/credentials/resolve" and request.method == "POST":
            return httpx.Response(
                200, json={"provider": "dropbox", "version": "v1", "refresh_token": "rt", "expires_at": None}
            )
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
