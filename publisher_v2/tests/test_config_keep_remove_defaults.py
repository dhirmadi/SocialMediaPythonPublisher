"""Keep/Remove folder defaults — env-only (#97 stage 4: INI removed)."""

from __future__ import annotations

import json

import pytest

from publisher_v2.config.loader import load_application_config


@pytest.fixture
def mock_env(monkeypatch):
    monkeypatch.setattr("publisher_v2.config.loader.load_dotenv", lambda *args, **kwargs: None)
    for key in ("EMAIL_SERVER", "CONTENT_SETTINGS", "CAPTIONFILE_SETTINGS", "CONFIRMATION_SETTINGS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DROPBOX_APP_KEY", "key")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "secret")
    monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "token")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-key")
    monkeypatch.setenv("PUBLISHERS", "[]")
    monkeypatch.setenv("OPENAI_SETTINGS", "{}")


def test_defaults_applied_when_omitted(mock_env, monkeypatch):
    monkeypatch.setenv("STORAGE_PATHS", json.dumps({"root": "/photos"}))

    config = load_application_config()

    assert config.dropbox.folder_keep == "/photos/keep"
    assert config.dropbox.folder_remove == "/photos/reject"


def test_explicit_values_override_defaults(mock_env, monkeypatch):
    monkeypatch.setenv("STORAGE_PATHS", json.dumps({"root": "/photos", "keep": "love", "remove": "hate"}))

    config = load_application_config()

    assert config.dropbox.folder_keep == "/photos/love"
    assert config.dropbox.folder_remove == "/photos/hate"


def test_absolute_paths_kept_as_is(mock_env, monkeypatch):
    monkeypatch.setenv(
        "STORAGE_PATHS", json.dumps({"root": "/photos", "keep": "/elsewhere/keep", "remove": "/elsewhere/reject"})
    )

    config = load_application_config()

    assert config.dropbox.folder_keep == "/elsewhere/keep"
    assert config.dropbox.folder_remove == "/elsewhere/reject"
