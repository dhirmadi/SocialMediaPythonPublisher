"""
Tests for Stories 02-05: JSON environment variable helper functions.

This module tests the helper functions introduced for parsing JSON-based
environment variables: PUBLISHERS, EMAIL_SERVER, STORAGE_PATHS, and the
OpenAI/metadata settings.
"""

from __future__ import annotations

import configparser
import os
from unittest import mock

import pytest

from publisher_v2.config.loader import (
    _load_email_server_from_env,
    _load_storage_paths_from_env,
    _load_openai_settings_from_env,
    _load_captionfile_settings_from_env,
    _load_confirmation_settings_from_env,
    _load_content_settings_from_env,
    _load_publishers_from_env,
    _resolve_path,
    _validate_path_no_traversal,
    log_config_source,
    log_deprecation_warning,
)
from publisher_v2.core.exceptions import ConfigurationError


# =============================================================================
# Story 03: Email Server Tests
# =============================================================================


class TestLoadEmailServerFromEnv:
    """Tests for _load_email_server_from_env function."""

    def test_returns_none_when_unset(self):
        """When EMAIL_SERVER is not set, returns None."""
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("EMAIL_SERVER", None)
            result = _load_email_server_from_env()
            assert result is None

    def test_returns_none_when_empty(self):
        """When EMAIL_SERVER is empty string, returns None."""
        with mock.patch.dict(os.environ, {"EMAIL_SERVER": ""}, clear=True):
            result = _load_email_server_from_env()
            assert result is None

    def test_parses_minimal_config(self):
        """Parses EMAIL_SERVER with only required sender field."""
        env_value = '{"sender": "bot@example.com"}'
        with mock.patch.dict(os.environ, {"EMAIL_SERVER": env_value}, clear=True):
            result = _load_email_server_from_env()
            assert result == {
                "smtp_server": "smtp.gmail.com",  # default
                "smtp_port": 587,  # default
                "sender": "bot@example.com",
            }

    def test_parses_full_config(self):
        """Parses EMAIL_SERVER with all fields specified."""
        env_value = '{"smtp_server": "mail.custom.com", "smtp_port": 465, "sender": "noreply@custom.com"}'
        with mock.patch.dict(os.environ, {"EMAIL_SERVER": env_value}, clear=True):
            result = _load_email_server_from_env()
            assert result == {
                "smtp_server": "mail.custom.com",
                "smtp_port": 465,
                "sender": "noreply@custom.com",
            }

    def test_raises_when_sender_missing(self):
        """Raises ConfigurationError when sender is missing."""
        env_value = '{"smtp_server": "mail.custom.com"}'
        with mock.patch.dict(os.environ, {"EMAIL_SERVER": env_value}, clear=True):
            with pytest.raises(ConfigurationError, match="missing required field 'sender'"):
                _load_email_server_from_env()

    def test_raises_when_smtp_port_not_integer(self):
        """Raises ConfigurationError when smtp_port is not an integer."""
        env_value = '{"sender": "bot@example.com", "smtp_port": "not-a-number"}'
        with mock.patch.dict(os.environ, {"EMAIL_SERVER": env_value}, clear=True):
            with pytest.raises(ConfigurationError, match="smtp_port must be an integer"):
                _load_email_server_from_env()

    def test_raises_on_invalid_json(self):
        """Raises ConfigurationError on invalid JSON."""
        with mock.patch.dict(os.environ, {"EMAIL_SERVER": "{not valid json}"}, clear=True):
            with pytest.raises(ConfigurationError, match="Invalid JSON in EMAIL_SERVER"):
                _load_email_server_from_env()


# =============================================================================
# Story 04: Storage Paths Tests
# =============================================================================


class TestResolvePath:
    """Tests for _resolve_path function."""

    def test_resolves_relative_path(self):
        """Relative paths are resolved against base."""
        assert _resolve_path("/dropbox/images", "archive") == "/dropbox/images/archive"

    def test_resolves_absolute_path(self):
        """Absolute paths are returned as-is."""
        assert _resolve_path("/dropbox/images", "/other/archive") == "/other/archive"

    def test_handles_trailing_slash_in_base(self):
        """Trailing slashes in base are handled correctly."""
        assert _resolve_path("/dropbox/images/", "archive") == "/dropbox/images/archive"


class TestValidatePathNoTraversal:
    """Tests for _validate_path_no_traversal function."""

    def test_allows_normal_path(self):
        """Normal paths pass validation."""
        _validate_path_no_traversal("/dropbox/images", "root")  # No exception

    def test_rejects_path_with_double_dot(self):
        """Paths containing '..' are rejected."""
        with pytest.raises(ConfigurationError, match="contains '..' which is not allowed"):
            _validate_path_no_traversal("/dropbox/../etc", "root")

    def test_allows_path_with_dots_in_filename(self):
        """Paths with dots in filenames are allowed."""
        _validate_path_no_traversal("/dropbox/file.name.ext", "root")  # No exception


class TestLoadStoragePathsFromEnv:
    """Tests for _load_storage_paths_from_env function."""

    def test_returns_none_when_unset(self):
        """When STORAGE_PATHS is not set, returns None."""
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("STORAGE_PATHS", None)
            result = _load_storage_paths_from_env()
            assert result is None

    def test_parses_minimal_config(self):
        """Parses STORAGE_PATHS with only required root field."""
        env_value = '{"root": "/Dropbox/MyPhotos"}'
        with mock.patch.dict(os.environ, {"STORAGE_PATHS": env_value}, clear=True):
            result = _load_storage_paths_from_env()
            assert result == {
                "root": "/Dropbox/MyPhotos",
                "archive": "/Dropbox/MyPhotos/archive",  # default
                "keep": "/Dropbox/MyPhotos/keep",  # default
                "remove": "/Dropbox/MyPhotos/reject",  # default
            }

    def test_parses_full_config(self):
        """Parses STORAGE_PATHS with all fields specified."""
        env_value = '{"root": "/Photos", "archive": "sent", "keep": "favorites", "remove": "trash"}'
        with mock.patch.dict(os.environ, {"STORAGE_PATHS": env_value}, clear=True):
            result = _load_storage_paths_from_env()
            assert result == {
                "root": "/Photos",
                "archive": "/Photos/sent",
                "keep": "/Photos/favorites",
                "remove": "/Photos/trash",
            }

    def test_parses_absolute_subpaths(self):
        """Absolute paths for subfolders are preserved."""
        env_value = '{"root": "/Photos", "archive": "/Archive/sent"}'
        with mock.patch.dict(os.environ, {"STORAGE_PATHS": env_value}, clear=True):
            result = _load_storage_paths_from_env()
            assert result["archive"] == "/Archive/sent"

    def test_raises_when_root_missing(self):
        """Raises ConfigurationError when root is missing."""
        env_value = '{"archive": "sent"}'
        with mock.patch.dict(os.environ, {"STORAGE_PATHS": env_value}, clear=True):
            with pytest.raises(ConfigurationError, match="missing required field 'root'"):
                _load_storage_paths_from_env()

    def test_raises_when_root_not_absolute(self):
        """Raises ConfigurationError when root is not absolute."""
        env_value = '{"root": "relative/path"}'
        with mock.patch.dict(os.environ, {"STORAGE_PATHS": env_value}, clear=True):
            with pytest.raises(ConfigurationError, match="must be an absolute path"):
                _load_storage_paths_from_env()

    def test_raises_when_root_has_traversal(self):
        """Raises ConfigurationError when root contains '..'."""
        env_value = '{"root": "/Dropbox/../etc"}'
        with mock.patch.dict(os.environ, {"STORAGE_PATHS": env_value}, clear=True):
            with pytest.raises(ConfigurationError, match="contains '..' which is not allowed"):
                _load_storage_paths_from_env()

    def test_raises_when_archive_has_traversal(self):
        """Raises ConfigurationError when archive contains '..'."""
        env_value = '{"root": "/Dropbox", "archive": "../etc"}'
        with mock.patch.dict(os.environ, {"STORAGE_PATHS": env_value}, clear=True):
            with pytest.raises(ConfigurationError, match="contains '..' which is not allowed"):
                _load_storage_paths_from_env()


# =============================================================================
# Story 05: OpenAI and Metadata Settings Tests
# =============================================================================


class TestLoadOpenAISettingsFromEnv:
    """Tests for _load_openai_settings_from_env function."""

    def test_returns_none_when_unset(self):
        """When OPENAI_SETTINGS is not set, returns None."""
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("OPENAI_SETTINGS", None)
            result = _load_openai_settings_from_env()
            assert result is None

    def test_parses_minimal_config(self):
        """Parses OPENAI_SETTINGS with empty object, using defaults."""
        with mock.patch.dict(os.environ, {"OPENAI_SETTINGS": "{}"}, clear=True):
            result = _load_openai_settings_from_env()
            assert result["vision_model"] == "gpt-4o"
            assert result["caption_model"] == "gpt-4o-mini"
            assert result["sd_caption_enabled"] is True

    def test_parses_full_config(self):
        """Parses OPENAI_SETTINGS with all fields specified."""
        env_value = """{
            "vision_model": "gpt-4-vision",
            "caption_model": "gpt-3.5-turbo",
            "system_prompt": "Custom system prompt",
            "role_prompt": "Custom role prompt",
            "sd_caption_enabled": false,
            "sd_caption_single_call_enabled": false,
            "sd_caption_model": "gpt-4o-mini",
            "sd_caption_system_prompt": "SD system",
            "sd_caption_role_prompt": "SD role"
        }"""
        with mock.patch.dict(os.environ, {"OPENAI_SETTINGS": env_value}, clear=True):
            result = _load_openai_settings_from_env()
            assert result["vision_model"] == "gpt-4-vision"
            assert result["caption_model"] == "gpt-3.5-turbo"
            assert result["system_prompt"] == "Custom system prompt"
            assert result["sd_caption_enabled"] is False


class TestLoadCaptionfileSettingsFromEnv:
    """Tests for _load_captionfile_settings_from_env function."""

    def test_returns_none_when_unset(self):
        """When CAPTIONFILE_SETTINGS is not set, returns None."""
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CAPTIONFILE_SETTINGS", None)
            result = _load_captionfile_settings_from_env()
            assert result is None

    def test_parses_config(self):
        """Parses CAPTIONFILE_SETTINGS with fields specified."""
        env_value = '{"extended_metadata_enabled": true, "artist_alias": "PhotoArtist"}'
        with mock.patch.dict(os.environ, {"CAPTIONFILE_SETTINGS": env_value}, clear=True):
            result = _load_captionfile_settings_from_env()
            assert result["extended_metadata_enabled"] is True
            assert result["artist_alias"] == "PhotoArtist"

    def test_uses_defaults(self):
        """Uses defaults when fields not specified."""
        with mock.patch.dict(os.environ, {"CAPTIONFILE_SETTINGS": "{}"}, clear=True):
            result = _load_captionfile_settings_from_env()
            assert result["extended_metadata_enabled"] is False
            assert result["artist_alias"] is None


class TestLoadConfirmationSettingsFromEnv:
    """Tests for _load_confirmation_settings_from_env function."""

    def test_returns_none_when_unset(self):
        """When CONFIRMATION_SETTINGS is not set, returns None."""
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CONFIRMATION_SETTINGS", None)
            result = _load_confirmation_settings_from_env()
            assert result is None

    def test_parses_config(self):
        """Parses CONFIRMATION_SETTINGS with fields specified."""
        env_value = '{"confirmation_to_sender": false, "confirmation_tags_count": 10, "confirmation_tags_nature": "nouns only"}'
        with mock.patch.dict(os.environ, {"CONFIRMATION_SETTINGS": env_value}, clear=True):
            result = _load_confirmation_settings_from_env()
            assert result["confirmation_to_sender"] is False
            assert result["confirmation_tags_count"] == 10
            assert result["confirmation_tags_nature"] == "nouns only"


class TestLoadContentSettingsFromEnv:
    """Tests for _load_content_settings_from_env function."""

    def test_returns_none_when_unset(self):
        """When CONTENT_SETTINGS is not set, returns None."""
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("CONTENT_SETTINGS", None)
            result = _load_content_settings_from_env()
            assert result is None

    def test_parses_config(self):
        """Parses CONTENT_SETTINGS with fields specified."""
        env_value = '{"hashtag_string": "#photo #art", "archive": false, "debug": true}'
        with mock.patch.dict(os.environ, {"CONTENT_SETTINGS": env_value}, clear=True):
            result = _load_content_settings_from_env()
            assert result["hashtag_string"] == "#photo #art"
            assert result["archive"] is False
            assert result["debug"] is True

    def test_uses_defaults(self):
        """Uses defaults when fields not specified."""
        with mock.patch.dict(os.environ, {"CONTENT_SETTINGS": "{}"}, clear=True):
            result = _load_content_settings_from_env()
            assert result["hashtag_string"] == ""
            assert result["archive"] is True
            assert result["debug"] is False


# =============================================================================
# Story 02: Publishers Tests
# =============================================================================


@pytest.fixture
def mock_configparser():
    """Create a mock ConfigParser with Email section."""
    cp = configparser.ConfigParser()
    cp.add_section("Email")
    cp.set("Email", "sender", "sender@ini.com")
    cp.set("Email", "smtp_server", "smtp.ini.com")
    cp.set("Email", "smtp_port", "25")
    cp.set("Email", "confirmation_to_sender", "true")
    cp.set("Email", "confirmation_tags_count", "5")
    cp.set("Email", "confirmation_tags_nature", "ini tags nature")
    return cp


class TestLoadPublishersFromEnv:
    """Tests for _load_publishers_from_env function."""

    def test_telegram_publisher(self, mock_configparser):
        """Parses Telegram publisher from PUBLISHERS."""
        entries = [{"type": "telegram", "channel_id": "@test_channel"}]
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test-bot-token"}, clear=True):
            telegram, instagram, email, platforms = _load_publishers_from_env(
                entries, None, mock_configparser
            )
            assert telegram is not None
            assert telegram.bot_token == "test-bot-token"
            assert telegram.channel_id == "@test_channel"
            assert platforms.telegram_enabled is True
            assert instagram is None
            assert email is None

    def test_telegram_missing_bot_token_raises(self, mock_configparser):
        """Raises ConfigurationError when TELEGRAM_BOT_TOKEN is missing."""
        entries = [{"type": "telegram", "channel_id": "@test_channel"}]
        with mock.patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError, match="TELEGRAM_BOT_TOKEN required"):
                _load_publishers_from_env(entries, None, mock_configparser)

    def test_telegram_missing_channel_id_raises(self, mock_configparser):
        """Raises ConfigurationError when channel_id is missing."""
        entries = [{"type": "telegram"}]
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test"}, clear=True):
            with pytest.raises(ConfigurationError, match="missing required field 'channel_id'"):
                _load_publishers_from_env(entries, None, mock_configparser)

    def test_fetlife_publisher_with_email_server(self, mock_configparser):
        """Parses FetLife publisher using EMAIL_SERVER settings."""
        entries = [{"type": "fetlife", "recipient": "user@fetlife.com", "caption_target": "body"}]
        email_server = {"smtp_server": "smtp.env.com", "smtp_port": 587, "sender": "sender@env.com"}
        with mock.patch.dict(os.environ, {"EMAIL_PASSWORD": "secret123"}, clear=True):
            telegram, instagram, email, platforms = _load_publishers_from_env(
                entries, email_server, mock_configparser
            )
            assert email is not None
            assert email.smtp_server == "smtp.env.com"
            assert email.smtp_port == 587
            assert email.sender == "sender@env.com"
            assert email.recipient == "user@fetlife.com"
            assert email.caption_target == "body"
            assert platforms.email_enabled is True

    def test_fetlife_publisher_fallback_to_ini(self, mock_configparser):
        """Parses FetLife publisher falling back to INI settings."""
        entries = [{"type": "fetlife", "recipient": "user@fetlife.com"}]
        with mock.patch.dict(os.environ, {"EMAIL_PASSWORD": "secret123"}, clear=True):
            telegram, instagram, email, platforms = _load_publishers_from_env(
                entries, None, mock_configparser
            )
            assert email is not None
            assert email.smtp_server == "smtp.ini.com"
            assert email.smtp_port == 25
            assert email.sender == "sender@ini.com"

    def test_fetlife_missing_password_raises(self, mock_configparser):
        """Raises ConfigurationError when EMAIL_PASSWORD is missing."""
        entries = [{"type": "fetlife", "recipient": "user@fetlife.com"}]
        with mock.patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError, match="EMAIL_PASSWORD required"):
                _load_publishers_from_env(entries, None, mock_configparser)

    def test_fetlife_missing_recipient_raises(self, mock_configparser):
        """Raises ConfigurationError when recipient is missing."""
        entries = [{"type": "fetlife"}]
        with mock.patch.dict(os.environ, {"EMAIL_PASSWORD": "secret"}, clear=True):
            with pytest.raises(ConfigurationError, match="missing required field 'recipient'"):
                _load_publishers_from_env(entries, None, mock_configparser)

    def test_instagram_publisher(self, mock_configparser):
        """Parses Instagram publisher from PUBLISHERS."""
        entries = [{"type": "instagram", "username": "photo_account"}]
        with mock.patch.dict(os.environ, {"INSTA_PASSWORD": "insta-secret"}, clear=True):
            telegram, instagram, email, platforms = _load_publishers_from_env(
                entries, None, mock_configparser
            )
            assert instagram is not None
            assert instagram.username == "photo_account"
            assert instagram.password == "insta-secret"
            assert platforms.instagram_enabled is True

    def test_instagram_missing_password_raises(self, mock_configparser):
        """Raises ConfigurationError when INSTA_PASSWORD is missing."""
        entries = [{"type": "instagram", "username": "photo_account"}]
        with mock.patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ConfigurationError, match="INSTA_PASSWORD required"):
                _load_publishers_from_env(entries, None, mock_configparser)

    def test_instagram_missing_username_raises(self, mock_configparser):
        """Raises ConfigurationError when username is missing."""
        entries = [{"type": "instagram"}]
        with mock.patch.dict(os.environ, {"INSTA_PASSWORD": "secret"}, clear=True):
            with pytest.raises(ConfigurationError, match="missing required field 'username'"):
                _load_publishers_from_env(entries, None, mock_configparser)

    def test_multiple_publishers(self, mock_configparser):
        """Parses multiple publishers correctly."""
        entries = [
            {"type": "telegram", "channel_id": "@channel"},
            {"type": "fetlife", "recipient": "user@fetlife.com"},
        ]
        email_server = {"smtp_server": "smtp.test.com", "smtp_port": 587, "sender": "bot@test.com"}
        with mock.patch.dict(
            os.environ,
            {"TELEGRAM_BOT_TOKEN": "bot-token", "EMAIL_PASSWORD": "email-pw"},
            clear=True,
        ):
            telegram, instagram, email, platforms = _load_publishers_from_env(
                entries, email_server, mock_configparser
            )
            assert telegram is not None
            assert email is not None
            assert instagram is None
            assert platforms.telegram_enabled is True
            assert platforms.email_enabled is True
            assert platforms.instagram_enabled is False

    def test_duplicate_publisher_type_raises(self, mock_configparser):
        """Raises ConfigurationError when duplicate publisher types exist."""
        entries = [
            {"type": "telegram", "channel_id": "@channel1"},
            {"type": "telegram", "channel_id": "@channel2"},
        ]
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token"}, clear=True):
            with pytest.raises(ConfigurationError, match="Duplicate publisher type 'telegram'"):
                _load_publishers_from_env(entries, None, mock_configparser)

    def test_unknown_publisher_type_logs_warning(self, mock_configparser, caplog):
        """Unknown publisher types are skipped with a warning."""
        entries = [{"type": "unknown_platform", "channel": "test"}]
        with mock.patch.dict(os.environ, {}, clear=True):
            telegram, instagram, email, platforms = _load_publishers_from_env(
                entries, None, mock_configparser
            )
            assert telegram is None
            assert instagram is None
            assert email is None
            assert "Unknown publisher type 'unknown_platform'" in caplog.text

    def test_empty_publishers_list(self, mock_configparser):
        """Empty PUBLISHERS list results in all publishers disabled."""
        entries = []
        with mock.patch.dict(os.environ, {}, clear=True):
            telegram, instagram, email, platforms = _load_publishers_from_env(
                entries, None, mock_configparser
            )
            assert telegram is None
            assert instagram is None
            assert email is None
            assert platforms.telegram_enabled is False
            assert platforms.instagram_enabled is False
            assert platforms.email_enabled is False

    def test_fetlife_with_confirmation_settings_from_env(self, mock_configparser):
        """FetLife publisher uses CONFIRMATION_SETTINGS from env when available."""
        entries = [{"type": "fetlife", "recipient": "user@fetlife.com"}]
        email_server = {"smtp_server": "smtp.test.com", "smtp_port": 587, "sender": "bot@test.com"}
        with mock.patch.dict(
            os.environ,
            {
                "EMAIL_PASSWORD": "secret",
                "CONFIRMATION_SETTINGS": '{"confirmation_to_sender": false, "confirmation_tags_count": 3}',
            },
            clear=True,
        ):
            telegram, instagram, email, platforms = _load_publishers_from_env(
                entries, email_server, mock_configparser
            )
            assert email is not None
            assert email.confirmation_to_sender is False
            assert email.confirmation_tags_count == 3


# =============================================================================
# Story 06: Deprecation Logging Tests
# =============================================================================


class TestLogConfigSource:
    """Tests for log_config_source function."""

    def test_logs_env_vars_source(self, caplog):
        """Logs info when config is fully env-based."""
        import logging
        caplog.set_level(logging.INFO)
        log_config_source("env_vars", publishers_count=2, storage_source="STORAGE_PATHS")
        assert "Config source: env_vars" in caplog.text
        assert "publishers=2" in caplog.text
        assert "storage=STORAGE_PATHS" in caplog.text

    def test_logs_ini_fallback_source(self, caplog):
        """Logs warning when INI fallback is used."""
        import logging
        caplog.set_level(logging.WARNING)
        log_config_source(
            "ini_fallback",
            ini_sections_used=["Content", "Email"],
            publishers_count=1,
            storage_source="INI",
        )
        assert "Config source: ini_fallback" in caplog.text
        assert "migrate to env vars" in caplog.text
        assert "Content, Email" in caplog.text
        assert "publishers=1" in caplog.text
        assert "storage=INI" in caplog.text


class TestLogDeprecationWarning:
    """Tests for log_deprecation_warning function."""

    def test_logs_deprecation_with_sections(self, caplog):
        """Logs deprecation warning with INI sections used."""
        import logging
        caplog.set_level(logging.WARNING)
        log_deprecation_warning(["Content", "Email", "openAI"])
        assert "DEPRECATION" in caplog.text
        assert "INI-based config is deprecated" in caplog.text
        assert "Content" in caplog.text
        assert "Email" in caplog.text
        assert "openAI" in caplog.text

    def test_no_log_when_no_sections(self, caplog):
        """Does not log when no INI sections used."""
        import logging
        caplog.set_level(logging.WARNING)
        log_deprecation_warning([])
        assert "DEPRECATION" not in caplog.text

