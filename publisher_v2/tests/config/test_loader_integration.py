"""
Integration tests for env-first configuration loading.

Tests the full load_application_config() function with JSON env vars.
"""

from __future__ import annotations

import os
import tempfile
from unittest import mock

import pytest

from publisher_v2.config.loader import load_application_config
from publisher_v2.core.exceptions import ConfigurationError


@pytest.fixture
def empty_env_file(tmp_path):
    """Create an empty .env file to prevent loading workspace .env."""
    env_file = tmp_path / ".env"
    env_file.write_text("")
    return str(env_file)


@pytest.fixture
def minimal_ini_file():
    """Create a minimal INI file for testing."""
    ini_content = """
[Dropbox]
image_folder = /TestPhotos

[Content]
telegram = false
instagram = false
fetlife = false
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
        f.write(ini_content)
        yield f.name
    os.unlink(f.name)


@pytest.fixture
def full_ini_file():
    """Create a full INI file for testing INI fallback."""
    ini_content = """\
[Dropbox]
image_folder = /IniPhotos
archive = ini_archive
folder_keep = ini_keep
folder_remove = ini_remove

[Content]
telegram = false
instagram = false
fetlife = false
hashtag_string = #fromini
archive = true
debug = false

[openAI]
vision_model = gpt-4o
caption_model = gpt-4o-mini
system_prompt = INI system prompt
role_prompt = INI role prompt

[CaptionFile]
extended_metadata_enabled = true
artist_alias = INI Artist
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".ini", delete=False) as f:
        f.write(ini_content)
        f.flush()
        yield f.name
    os.unlink(f.name)


@pytest.fixture
def base_env_vars():
    """Base environment variables required for all tests."""
    return {
        "DROPBOX_APP_KEY": "test-app-key",
        "DROPBOX_APP_SECRET": "test-app-secret",
        "DROPBOX_REFRESH_TOKEN": "test-refresh-token",
        "OPENAI_API_KEY": "sk-test-key",
    }


class TestEnvFirstStoragePaths:
    """Test STORAGE_PATHS env var takes precedence over INI."""

    def test_storage_paths_env_overrides_ini(self, full_ini_file, base_env_vars, empty_env_file):
        """STORAGE_PATHS env var should override INI [Dropbox] section."""
        env = {
            **base_env_vars,
            "STORAGE_PATHS": '{"root": "/EnvPhotos", "archive": "/EnvPhotos/sent", "keep": "/EnvPhotos/favorites", "remove": "/EnvPhotos/trash"}',
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_application_config(full_ini_file, empty_env_file)
            assert config.dropbox.image_folder == "/EnvPhotos"
            assert config.dropbox.archive_folder == "/EnvPhotos/sent"
            assert config.dropbox.folder_keep == "/EnvPhotos/favorites"
            assert config.dropbox.folder_remove == "/EnvPhotos/trash"

    def test_falls_back_to_ini_when_storage_paths_not_set(self, full_ini_file, base_env_vars, caplog, empty_env_file):
        """Falls back to INI when STORAGE_PATHS not set, emits deprecation warning."""
        import logging
        caplog.set_level(logging.WARNING)
        with mock.patch.dict(os.environ, base_env_vars, clear=True):
            config = load_application_config(full_ini_file, empty_env_file)
            assert config.dropbox.image_folder == "/IniPhotos"
            assert config.dropbox.archive_folder == "ini_archive"
            assert "DEPRECATION" in caplog.text
            assert "Dropbox" in caplog.text


class TestEnvFirstPublishers:
    """Test PUBLISHERS env var takes precedence over INI toggles."""

    def test_publishers_env_enables_telegram(self, minimal_ini_file, base_env_vars, empty_env_file):
        """PUBLISHERS env var should enable Telegram when entry present."""
        env = {
            **base_env_vars,
            "PUBLISHERS": '[{"type": "telegram", "channel_id": "@test_channel"}]',
            "TELEGRAM_BOT_TOKEN": "test-bot-token",
            "STORAGE_PATHS": '{"root": "/Photos"}',
            "OPENAI_SETTINGS": "{}",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_application_config(minimal_ini_file, empty_env_file)
            assert config.platforms.telegram_enabled is True
            assert config.telegram is not None
            assert config.telegram.channel_id == "@test_channel"
            assert config.telegram.bot_token == "test-bot-token"

    def test_publishers_env_enables_fetlife(self, minimal_ini_file, base_env_vars, empty_env_file):
        """PUBLISHERS env var should enable FetLife when entry present."""
        env = {
            **base_env_vars,
            "PUBLISHERS": '[{"type": "fetlife", "recipient": "user@fetlife.com", "caption_target": "body"}]',
            "EMAIL_PASSWORD": "test-email-password",
            "EMAIL_SERVER": '{"sender": "bot@test.com", "smtp_server": "smtp.test.com", "smtp_port": 587}',
            "STORAGE_PATHS": '{"root": "/Photos"}',
            "OPENAI_SETTINGS": "{}",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_application_config(minimal_ini_file, empty_env_file)
            assert config.platforms.email_enabled is True
            assert config.email is not None
            assert config.email.recipient == "user@fetlife.com"
            assert config.email.caption_target == "body"
            assert config.email.smtp_server == "smtp.test.com"

    def test_empty_publishers_disables_all(self, minimal_ini_file, base_env_vars, empty_env_file):
        """Empty PUBLISHERS array should disable all publishers."""
        env = {
            **base_env_vars,
            "PUBLISHERS": "[]",
            "STORAGE_PATHS": '{"root": "/Photos"}',
            "OPENAI_SETTINGS": "{}",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_application_config(minimal_ini_file, empty_env_file)
            assert config.platforms.telegram_enabled is False
            assert config.platforms.instagram_enabled is False
            assert config.platforms.email_enabled is False
            assert config.telegram is None
            assert config.instagram is None
            assert config.email is None


class TestEnvFirstOpenAI:
    """Test OPENAI_SETTINGS env var takes precedence over INI."""

    def test_openai_settings_env_overrides_ini(self, full_ini_file, base_env_vars, empty_env_file):
        """OPENAI_SETTINGS env var should override INI [openAI] section."""
        env = {
            **base_env_vars,
            "OPENAI_SETTINGS": '{"vision_model": "gpt-4-vision", "caption_model": "gpt-3.5-turbo", "system_prompt": "ENV system"}',
            "STORAGE_PATHS": '{"root": "/Photos"}',
            "PUBLISHERS": "[]",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_application_config(full_ini_file, empty_env_file)
            assert config.openai.vision_model == "gpt-4-vision"
            assert config.openai.caption_model == "gpt-3.5-turbo"
            assert config.openai.system_prompt == "ENV system"

    def test_falls_back_to_ini_when_openai_settings_not_set(self, full_ini_file, base_env_vars, caplog, empty_env_file):
        """Falls back to INI when OPENAI_SETTINGS not set, uses INI values."""
        import logging
        caplog.set_level(logging.WARNING)
        env = {
            **base_env_vars,
            "STORAGE_PATHS": '{"root": "/Photos"}',
            "PUBLISHERS": "[]",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_application_config(full_ini_file, empty_env_file)
            # Should use values from INI [openAI] section
            assert config.openai.vision_model == "gpt-4o"
            assert config.openai.caption_model == "gpt-4o-mini"
            # Deprecation warning should mention openAI
            assert "openAI" in caplog.text


class TestEnvFirstContent:
    """Test CONTENT_SETTINGS env var takes precedence over INI."""

    def test_content_settings_env_overrides_ini(self, full_ini_file, base_env_vars, empty_env_file):
        """CONTENT_SETTINGS env var should override INI [Content] hashtag/archive/debug."""
        env = {
            **base_env_vars,
            "CONTENT_SETTINGS": '{"hashtag_string": "#fromenv", "archive": false, "debug": true}',
            "STORAGE_PATHS": '{"root": "/Photos"}',
            "PUBLISHERS": "[]",
            "OPENAI_SETTINGS": "{}",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_application_config(full_ini_file, empty_env_file)
            assert config.content.hashtag_string == "#fromenv"
            assert config.content.archive is False
            assert config.content.debug is True


class TestEnvFirstCaptionFile:
    """Test CAPTIONFILE_SETTINGS env var takes precedence over INI."""

    def test_captionfile_settings_env_overrides_ini(self, full_ini_file, base_env_vars, empty_env_file):
        """CAPTIONFILE_SETTINGS env var should override INI [CaptionFile] section."""
        env = {
            **base_env_vars,
            "CAPTIONFILE_SETTINGS": '{"extended_metadata_enabled": false, "artist_alias": "ENV Artist"}',
            "STORAGE_PATHS": '{"root": "/Photos"}',
            "PUBLISHERS": "[]",
            "OPENAI_SETTINGS": "{}",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_application_config(full_ini_file, empty_env_file)
            assert config.captionfile.extended_metadata_enabled is False
            assert config.captionfile.artist_alias == "ENV Artist"


class TestDeprecationWarnings:
    """Test deprecation warnings are emitted when INI fallback is used."""

    def test_no_deprecation_when_all_env_vars_set(self, minimal_ini_file, base_env_vars, caplog, empty_env_file):
        """No deprecation warning when all config comes from env vars."""
        import logging
        caplog.set_level(logging.WARNING)
        env = {
            **base_env_vars,
            "STORAGE_PATHS": '{"root": "/Photos"}',
            "PUBLISHERS": "[]",
            "OPENAI_SETTINGS": "{}",
            "CONTENT_SETTINGS": "{}",
            "CAPTIONFILE_SETTINGS": "{}",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            load_application_config(minimal_ini_file, empty_env_file)
            assert "DEPRECATION" not in caplog.text

    def test_deprecation_emitted_when_ini_used(self, full_ini_file, base_env_vars, caplog, empty_env_file):
        """Deprecation warning emitted when INI sections are used."""
        import logging
        caplog.set_level(logging.WARNING)
        with mock.patch.dict(os.environ, base_env_vars, clear=True):
            load_application_config(full_ini_file, empty_env_file)
            assert "DEPRECATION" in caplog.text
            assert "INI-based config is deprecated" in caplog.text


class TestConfigSourceLogging:
    """Test config source is logged correctly."""

    def test_logs_env_vars_source(self, minimal_ini_file, base_env_vars, caplog, empty_env_file):
        """Logs 'env_vars' source when all config from env."""
        import logging
        caplog.set_level(logging.INFO)
        env = {
            **base_env_vars,
            "STORAGE_PATHS": '{"root": "/Photos"}',
            "PUBLISHERS": "[]",
            "OPENAI_SETTINGS": "{}",
            "CONTENT_SETTINGS": "{}",
            "CAPTIONFILE_SETTINGS": "{}",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            load_application_config(minimal_ini_file, empty_env_file)
            assert "Config source: env_vars" in caplog.text

    def test_logs_ini_fallback_source(self, full_ini_file, base_env_vars, caplog, empty_env_file):
        """Logs 'ini_fallback' source when INI is used."""
        import logging
        caplog.set_level(logging.WARNING)
        with mock.patch.dict(os.environ, base_env_vars, clear=True):
            load_application_config(full_ini_file, empty_env_file)
            assert "ini_fallback" in caplog.text


class TestMultiplePublishers:
    """Test multiple publishers in PUBLISHERS array."""

    def test_multiple_publishers_all_enabled(self, minimal_ini_file, base_env_vars, empty_env_file):
        """Multiple publishers in PUBLISHERS array all get enabled."""
        env = {
            **base_env_vars,
            "PUBLISHERS": """[
                {"type": "telegram", "channel_id": "@channel"},
                {"type": "fetlife", "recipient": "user@fetlife.com"}
            ]""",
            "TELEGRAM_BOT_TOKEN": "bot-token",
            "EMAIL_PASSWORD": "email-pw",
            "EMAIL_SERVER": '{"sender": "bot@test.com"}',
            "STORAGE_PATHS": '{"root": "/Photos"}',
            "OPENAI_SETTINGS": "{}",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_application_config(minimal_ini_file, empty_env_file)
            assert config.platforms.telegram_enabled is True
            assert config.platforms.email_enabled is True
            assert config.telegram is not None
            assert config.email is not None

