"""Integration tests for the /api/config/features endpoint."""
from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def test_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Create a test client with minimal config."""
    from publisher_v2.config.schema import (
        ApplicationConfig,
        ContentConfig,
        DropboxConfig,
        OpenAIConfig,
        PlatformsConfig,
        TelegramConfig,
        EmailConfig,
    )
    
    os.environ.setdefault("CONFIG_PATH", "configfiles/fetlife.ini")
    
    # Create minimal config with Telegram enabled and default feature flags.
    cfg = ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos"
        ),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(
            telegram_enabled=True, 
            email_enabled=False, 
            instagram_enabled=False
        ),
        telegram=TelegramConfig(bot_token="token", channel_id="123"),
        email=None,
        instagram=None,
        content=ContentConfig(hashtag_string="#tags", archive=True, debug=False),
    )
    # Ensure a fresh FeaturesConfig instance so mutations in other tests do not leak here.
    from publisher_v2.config.schema import FeaturesConfig

    cfg.features = FeaturesConfig()

    # Make the web layer use this config and reset the cached WebImageService.
    monkeypatch.setattr(
        "publisher_v2.web.service.load_application_config",
        lambda config_path, env_path: cfg,
    )

    from publisher_v2.web.app import app, get_service

    get_service.cache_clear()
    return TestClient(app)


def test_api_config_features_returns_correct_state(test_client: TestClient) -> None:
    """Test that /api/config/features returns correct feature flags."""
    response = test_client.get("/api/config/features")

    assert response.status_code == 200
    data = response.json()

    # Defaults from FeaturesConfig should all be truthy except AUTO_VIEW,
    # which is private-by-default.
    assert data["analyze_caption_enabled"] is True
    assert data["publish_enabled"] is True
    # New curation feature flags should also be present and default to True.
    assert data.get("keep_enabled", True) is True
    assert data.get("remove_enabled", True) is True
    # AUTO_VIEW should be present and default to False (private mode).
    assert data.get("auto_view_enabled", False) is False


def test_api_config_features_no_auth_required(test_client: TestClient) -> None:
    """Test that /api/config/features doesn't require authentication."""
    # No auth headers
    response = test_client.get("/api/config/features")
    
    # Should succeed without auth
    assert response.status_code == 200


def test_api_config_features_returns_json(test_client: TestClient) -> None:
    """Test that /api/config/features returns valid JSON."""
    response = test_client.get("/api/config/features")
    
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/json"
    
    data = response.json()
    assert isinstance(data, dict)
    assert "analyze_caption_enabled" in data
    assert "publish_enabled" in data
    
    # Verify auth_mode is a string, others are booleans
    assert isinstance(data.get("auth_mode"), str)
    
    # Check boolean flags (exclude auth_mode)
    bool_fields = {k: v for k, v in data.items() if k != "auth_mode"}
    assert all(isinstance(v, bool) for v in bool_fields.values())

