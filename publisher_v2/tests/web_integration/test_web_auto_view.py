from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    FeaturesConfig,
    OpenAIConfig,
    PlatformsConfig,
)


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch):
    """
    Create a TestClient with a minimal in-memory config and controllable AUTO_VIEW/admin settings.
    """

    def _make(auto_view: bool, admin_password: str | None) -> TestClient:
        # Ensure CONFIG_PATH is set so WebImageService initialization doesn't fail.
        os.environ.setdefault("CONFIG_PATH", "configfiles/fetlife.ini")

        cfg = ApplicationConfig(
            dropbox=DropboxConfig(
                app_key="k",
                app_secret="s",
                refresh_token="r",
                image_folder="/Photos",
            ),
            openai=OpenAIConfig(api_key="sk-test"),
            platforms=PlatformsConfig(
                telegram_enabled=False,
                instagram_enabled=False,
                email_enabled=False,
            ),
            features=FeaturesConfig(
                analyze_caption_enabled=True,
                publish_enabled=True,
                keep_enabled=True,
                remove_enabled=True,
                auto_view_enabled=auto_view,
            ),
            telegram=None,
            instagram=None,
            email=None,
            content=ContentConfig(hashtag_string="#tags", archive=True, debug=False),
        )

        # Make the web layer use our in-memory config instead of reading real files/env.
        monkeypatch.setattr(
            "publisher_v2.web.service.load_application_config",
            lambda config_path, env_path: cfg,
        )

        # Configure or clear admin password for this client.
        if admin_password is not None:
            monkeypatch.setenv("web_admin_pw", admin_password)
        else:
            monkeypatch.delenv("web_admin_pw", raising=False)
            
        # Ensure Auth0 is also disabled so is_admin_configured() returns False
        monkeypatch.delenv("AUTH0_DOMAIN", raising=False)
        monkeypatch.delenv("AUTH0_CLIENT_ID", raising=False)

        # Clear cached WebImageService so the patched loader is used.
        from publisher_v2.web.app import app, get_service

        get_service.cache_clear()
        return TestClient(app)

    return _make


def test_random_requires_admin_when_auto_view_disabled_and_admin_configured(
    make_client,
) -> None:
    client = make_client(auto_view=False, admin_password="secret-admin")

    # Without admin cookie, AUTO_VIEW disabled → should be rejected up front.
    res = client.get("/api/images/random")
    assert res.status_code == 403


def test_random_unavailable_when_auto_view_disabled_and_admin_unconfigured(
    make_client, monkeypatch
) -> None:
    # Explicitly patch is_admin_configured to False to avoid env var flakiness
    monkeypatch.setattr("publisher_v2.web.auth.is_admin_configured", lambda: False)
    monkeypatch.setattr("publisher_v2.web.app.is_admin_configured", lambda: False)

    client = make_client(auto_view=False, admin_password=None)
    
    # With AUTO_VIEW disabled and no admin configured, fail closed with 503.
    res = client.get("/api/images/random")
    assert res.status_code == 503


def test_random_allows_admin_when_auto_view_disabled(make_client, monkeypatch) -> None:
    from publisher_v2.web.app import get_service
    from publisher_v2.web.models import ImageResponse

    client = make_client(auto_view=False, admin_password="secret-admin")

    # Login to become admin.
    res = client.post("/api/admin/login", json={"password": "secret-admin"})
    assert res.status_code == 200

    # Stub get_random_image to avoid real Dropbox calls.
    svc = get_service()

    async def _fake_get_random_image() -> ImageResponse:
        return ImageResponse(
            filename="test.jpg",
            temp_url="https://example.com/test.jpg",
            sha256=None,
            caption="caption",
            sd_caption=None,
            metadata=None,
            has_sidecar=False,
        )

    monkeypatch.setattr(svc, "get_random_image", _fake_get_random_image)

    res = client.get("/api/images/random")
    assert res.status_code == 200
    data = res.json()
    assert data["filename"] == "test.jpg"


def test_random_open_when_auto_view_enabled(make_client, monkeypatch) -> None:
    from publisher_v2.web.app import get_service
    from publisher_v2.web.models import ImageResponse

    client = make_client(auto_view=True, admin_password=None)

    # Stub get_random_image so we don't hit Dropbox.
    svc = get_service()

    async def _fake_get_random_image() -> ImageResponse:
        return ImageResponse(
            filename="open.jpg",
            temp_url="https://example.com/open.jpg",
            sha256=None,
            caption="caption",
            sd_caption=None,
            metadata=None,
            has_sidecar=False,
        )

    monkeypatch.setattr(svc, "get_random_image", _fake_get_random_image)

    res = client.get("/api/images/random")
    assert res.status_code == 200
    data = res.json()
    assert data["filename"] == "open.jpg"
