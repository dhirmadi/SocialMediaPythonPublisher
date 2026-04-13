"""Tests for PUB-033 Story F: storage_provider field in /api/config/features.

The frontend needs to know whether the instance uses Dropbox or managed
storage to decide which data source and controls to render. This is exposed
as a single field in the existing /api/config/features endpoint.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    FeaturesConfig,
    ManagedStorageConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
)


def _make_dropbox_config() -> ApplicationConfig:
    return ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k",
            app_secret="s",
            refresh_token="r",
            image_folder="/Photos",
        ),
        storage_paths=StoragePathConfig(image_folder="/Photos"),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(),
        telegram=None,
        instagram=None,
        email=None,
        content=ContentConfig(),
        features=FeaturesConfig(),
    )


def _make_managed_config() -> ApplicationConfig:
    return ApplicationConfig(
        managed=ManagedStorageConfig(
            access_key_id="AKID",
            secret_access_key="SECRET",
            endpoint_url="https://r2.example.com",
            bucket="bucket",
        ),
        storage_paths=StoragePathConfig(image_folder="tenant/instance"),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(),
        telegram=None,
        instagram=None,
        email=None,
        content=ContentConfig(),
        features=FeaturesConfig(),
    )


def _client_with_config(monkeypatch: pytest.MonkeyPatch, cfg: ApplicationConfig) -> TestClient:
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)
    monkeypatch.setenv("CONFIG_SOURCE", "env")

    from publisher_v2.config.source import get_config_source

    get_config_source.cache_clear()

    monkeypatch.setattr(
        "publisher_v2.web.service.load_application_config",
        lambda config_path, env_path: cfg,
    )
    from publisher_v2.web.app import app, get_service

    get_service.cache_clear()
    return TestClient(app)


def test_features_config_includes_storage_provider_managed(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-F1: response includes storage_provider=managed for managed instances."""
    client = _client_with_config(monkeypatch, _make_managed_config())
    res = client.get("/api/config/features")
    assert res.status_code == 200
    data = res.json()
    assert data.get("storage_provider") == "managed"


def test_features_config_includes_storage_provider_dropbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-F1: response includes storage_provider=dropbox for Dropbox instances."""
    client = _client_with_config(monkeypatch, _make_dropbox_config())
    res = client.get("/api/config/features")
    assert res.status_code == 200
    data = res.json()
    assert data.get("storage_provider") == "dropbox"


def test_features_config_existing_fields_unchanged(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC-F2: all existing fields remain (backwards-compatible addition)."""
    client = _client_with_config(monkeypatch, _make_dropbox_config())
    res = client.get("/api/config/features")
    assert res.status_code == 200
    data = res.json()
    expected_keys = {
        "analyze_caption_enabled",
        "publish_enabled",
        "keep_enabled",
        "remove_enabled",
        "delete_enabled",
        "auto_view_enabled",
        "library_enabled",
        "auth_mode",
    }
    missing = expected_keys - data.keys()
    assert not missing, f"Missing existing keys: {missing}"
