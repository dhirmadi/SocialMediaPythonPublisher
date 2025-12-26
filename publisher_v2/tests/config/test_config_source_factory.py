from __future__ import annotations

import pytest

from publisher_v2.config.source import get_config_source, clear_config_source_cache
from publisher_v2.core.exceptions import ConfigurationError


def test_protocol_shape_smoke() -> None:
    # Just ensure factory returns an object with required methods.
    # Need minimal env-first config so EnvConfigSource can initialize.
    import os

    os.environ["STORAGE_PATHS"] = '{"root": "/Photos"}'
    os.environ["PUBLISHERS"] = "[]"
    os.environ["OPENAI_SETTINGS"] = "{}"
    os.environ["DROPBOX_APP_KEY"] = "test_app_key"
    os.environ["DROPBOX_APP_SECRET"] = "test_app_secret"
    os.environ["DROPBOX_REFRESH_TOKEN"] = "test_refresh_token"
    os.environ["OPENAI_API_KEY"] = "sk-test-key-for-testing-purposes-only"
    clear_config_source_cache()
    src = get_config_source()
    assert hasattr(src, "get_config")
    assert hasattr(src, "get_credentials")
    assert hasattr(src, "is_orchestrated")


def test_factory_selection(monkeypatch: pytest.MonkeyPatch, mock_dropbox_env, mock_openai_env) -> None:
    # Default: env-first
    monkeypatch.setenv("STORAGE_PATHS", '{"root": "/Photos"}')
    monkeypatch.setenv("PUBLISHERS", "[]")
    monkeypatch.setenv("OPENAI_SETTINGS", "{}")
    clear_config_source_cache()
    src = get_config_source()
    assert src.is_orchestrated() is False

    # Orchestrator when URL is set
    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orchestrator.test")
    monkeypatch.setenv("ORCHESTRATOR_SERVICE_TOKEN", "test-token")
    clear_config_source_cache()
    src2 = get_config_source()
    assert src2.is_orchestrated() is True

    # Override forces env-first even when URL set
    monkeypatch.setenv("CONFIG_SOURCE", "env")
    clear_config_source_cache()
    src3 = get_config_source()
    assert src3.is_orchestrated() is False


def test_factory_raises_when_url_set_but_token_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORCHESTRATOR_BASE_URL", "https://orchestrator.test")
    monkeypatch.delenv("ORCHESTRATOR_SERVICE_TOKEN", raising=False)
    clear_config_source_cache()
    with pytest.raises(ConfigurationError):
        _ = get_config_source()


