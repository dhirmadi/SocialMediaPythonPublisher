"""Keep/Remove folder configuration — env-only (#97 stage 4: INI removed)."""

from __future__ import annotations

import json

import pytest

from publisher_v2.config.loader import load_application_config
from publisher_v2.core.exceptions import ConfigurationError


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Baseline env-only config; keep/remove come from STORAGE_PATHS."""
    monkeypatch.setattr("publisher_v2.config.loader.load_dotenv", lambda *args, **kwargs: None)
    for key in [
        "FEATURE_ANALYZE_CAPTION",
        "FEATURE_PUBLISH",
        "FEATURE_KEEP_CURATE",
        "FEATURE_REMOVE_CURATE",
        "EMAIL_SERVER",
        "CONTENT_SETTINGS",
        "CAPTIONFILE_SETTINGS",
        "CONFIRMATION_SETTINGS",
        "STORAGE_PROVIDER",
    ]:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DROPBOX_APP_KEY", "k")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "s")
    monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "r")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("PUBLISHERS", "[]")
    monkeypatch.setenv("OPENAI_SETTINGS", "{}")
    monkeypatch.setenv("STORAGE_PATHS", json.dumps({"root": "/Photos", "archive": "archive"}))


def test_dropbox_keep_remove_from_storage_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        "STORAGE_PATHS",
        json.dumps({"root": "/Photos", "archive": "archive", "keep": "approve_env", "remove": "remove_env"}),
    )

    cfg = load_application_config()
    assert cfg.dropbox is not None
    assert cfg.dropbox.folder_keep == "/Photos/approve_env"
    assert cfg.dropbox.folder_remove == "/Photos/remove_env"


@pytest.mark.parametrize("value", ["../escape", "sub/../dir"])
def test_keep_folder_traversal_raises_configuration_error(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("STORAGE_PATHS", json.dumps({"root": "/Photos", "keep": value}))

    with pytest.raises(ConfigurationError):
        load_application_config()


def test_keep_remove_feature_flags_default_enabled() -> None:
    cfg = load_application_config()
    assert cfg.features.keep_enabled is True
    assert cfg.features.remove_enabled is True


def test_keep_remove_feature_flags_can_be_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FEATURE_KEEP_CURATE", "false")
    monkeypatch.setenv("FEATURE_REMOVE_CURATE", "0")

    cfg = load_application_config()
    assert cfg.features.keep_enabled is False
    assert cfg.features.remove_enabled is False
