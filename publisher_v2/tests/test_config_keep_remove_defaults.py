import os
import pytest
from unittest.mock import patch, MagicMock
from publisher_v2.config.loader import load_application_config
from publisher_v2.config.schema import DropboxConfig

@pytest.fixture
def mock_env(monkeypatch):
    # Clear env-first vars to ensure INI mode is used
    monkeypatch.delenv("STORAGE_PATHS", raising=False)
    monkeypatch.delenv("PUBLISHERS", raising=False)
    monkeypatch.delenv("OPENAI_SETTINGS", raising=False)
    monkeypatch.delenv("EMAIL_SERVER", raising=False)
    monkeypatch.delenv("CONTENT_SETTINGS", raising=False)
    monkeypatch.delenv("CAPTIONFILE_SETTINGS", raising=False)
    monkeypatch.delenv("CONFIRMATION_SETTINGS", raising=False)
    # Set minimal required env vars
    monkeypatch.setenv("DROPBOX_APP_KEY", "key")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "secret")
    monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "token")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-key")
    monkeypatch.setenv("WEB_ADMIN_PW", "secret")

def test_defaults_applied_when_missing_in_ini(mock_env, tmp_path):
    ini_content = """
[Dropbox]
image_folder = /photos
    """
    config_file = tmp_path / "test.ini"
    config_file.write_text(ini_content)
    
    config = load_application_config(str(config_file))
    
    assert config.dropbox.folder_keep == "keep"
    assert config.dropbox.folder_remove == "reject"

def test_legacy_alias_respected(mock_env, tmp_path):
    ini_content = """
[Dropbox]
image_folder = /photos
folder_reject = trash
    """
    config_file = tmp_path / "test.ini"
    config_file.write_text(ini_content)
    
    config = load_application_config(str(config_file))
    
    assert config.dropbox.folder_keep == "keep"
    assert config.dropbox.folder_remove == "trash"

def test_explicit_values_override_defaults(mock_env, tmp_path):
    ini_content = """
[Dropbox]
image_folder = /photos
folder_keep = love
folder_remove = hate
    """
    config_file = tmp_path / "test.ini"
    config_file.write_text(ini_content)
    
    config = load_application_config(str(config_file))
    
    assert config.dropbox.folder_keep == "love"
    assert config.dropbox.folder_remove == "hate"

def test_env_vars_override_defaults(mock_env, tmp_path, monkeypatch):
    monkeypatch.setenv("folder_keep", "env_keep")
    monkeypatch.setenv("folder_remove", "env_remove")
    
    ini_content = """
[Dropbox]
image_folder = /photos
    """
    config_file = tmp_path / "test.ini"
    config_file.write_text(ini_content)
    
    config = load_application_config(str(config_file))
    
    assert config.dropbox.folder_keep == "env_keep"
    assert config.dropbox.folder_remove == "env_remove"

