from __future__ import annotations

import os

import pytest

from publisher_v2.config.loader import load_application_config
from publisher_v2.core.exceptions import ConfigurationError


def _write_ini(tmp_path, content: str) -> str:
    cfg = tmp_path / "test.ini"
    cfg.write_text(content)
    return str(cfg)


@pytest.fixture(autouse=True)
def _clear_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure env overrides from the real environment do not leak into tests."""
    for key in [
        "DROPBOX_APP_KEY",
        "DROPBOX_APP_SECRET",
        "DROPBOX_REFRESH_TOKEN",
        "OPENAI_API_KEY",
        "FEATURE_ANALYZE_CAPTION",
        "FEATURE_PUBLISH",
        "FEATURE_KEEP_CURATE",
        "FEATURE_REMOVE_CURATE",
        "folder_keep",
        "folder_remove",
    ]:
        monkeypatch.delenv(key, raising=False)
    # Provide minimal required secrets for load_application_config.
    monkeypatch.setenv("DROPBOX_APP_KEY", "k")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "s")
    monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "r")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")


def test_dropbox_keep_remove_from_ini_and_env(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    ini = """
[Dropbox]
image_folder = /Photos
archive = archive
folder_keep = approve_ini
folder_remove = remove_ini

[openAI]
vision_model = gpt-4o

[Content]
archive = true
debug = false
"""
    cfg_path = _write_ini(tmp_path, ini)
    # Env overrides should win over INI.
    monkeypatch.setenv("folder_keep", "approve_env")
    monkeypatch.setenv("folder_remove", "remove_env")

    cfg = load_application_config(cfg_path)
    assert cfg.dropbox.folder_keep == "approve_env"
    assert cfg.dropbox.folder_remove == "remove_env"


def test_dropbox_folder_reject_aliases_folder_remove(tmp_path) -> None:
    ini = """
[Dropbox]
image_folder = /Photos
archive = archive
folder_reject = reject_folder

[openAI]
vision_model = gpt-4o

[Content]
archive = true
debug = false
"""
    cfg_path = _write_ini(tmp_path, ini)

    cfg = load_application_config(cfg_path)
    # Legacy folder_reject should populate folder_remove when explicit remove not set.
    assert cfg.dropbox.folder_remove == "reject_folder"


@pytest.mark.parametrize(
    "value",
    [
        "bad/name",
        "bad\\name",
        "../escape",
        "sub/dir",
    ],
)
def test_keep_remove_folder_invalid_values_raise_configuration_error(tmp_path, value: str) -> None:
    # Use only INI; env overrides are cleared by fixture.
    ini = f"""
[Dropbox]
image_folder = /Photos
archive = archive
folder_keep = {value}

[openAI]
vision_model = gpt-4o

[Content]
archive = true
debug = false
"""
    cfg_path = _write_ini(tmp_path, ini)

    with pytest.raises(ConfigurationError):
        load_application_config(cfg_path)


def test_keep_remove_feature_flags_default_enabled(tmp_path) -> None:
    ini = """
[Dropbox]
image_folder = /Photos
archive = archive

[openAI]
vision_model = gpt-4o

[Content]
archive = true
debug = false
"""
    cfg_path = _write_ini(tmp_path, ini)

    cfg = load_application_config(cfg_path)
    assert cfg.features.keep_enabled is True
    assert cfg.features.remove_enabled is True


def test_keep_remove_feature_flags_can_be_disabled(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    ini = """
[Dropbox]
image_folder = /Photos
archive = archive

[openAI]
vision_model = gpt-4o

[Content]
archive = true
debug = false
"""
    cfg_path = _write_ini(tmp_path, ini)
    monkeypatch.setenv("FEATURE_KEEP_CURATE", "false")
    monkeypatch.setenv("FEATURE_REMOVE_CURATE", "0")

    cfg = load_application_config(cfg_path)
    assert cfg.features.keep_enabled is False
    assert cfg.features.remove_enabled is False


