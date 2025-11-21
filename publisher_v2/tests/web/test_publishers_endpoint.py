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
    
    # Create minimal config with Telegram enabled
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
    
    monkeypatch.setattr(
        "publisher_v2.web.service.load_application_config",
        lambda config_path, env_path: cfg,
    )
    
    from publisher_v2.web.app import app
    return TestClient(app)


def test_api_config_features_returns_correct_state(test_client: TestClient) -> None:
    """Test that /api/config/features returns correct feature flags."""
    response = test_client.get("/api/config/features")
    
    assert response.status_code == 200
    data = response.json()
    
    assert data == {
        "analyze_caption_enabled": True,
        "publish_enabled": True,
    }


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
    assert all(isinstance(v, bool) for v in data.values())

