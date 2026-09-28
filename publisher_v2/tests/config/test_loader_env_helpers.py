"""
Tests for Stories 02-05: JSON environment variable helper functions.

This module tests the helper functions introduced for parsing JSON-based
environment variables: PUBLISHERS, EMAIL_SERVER, STORAGE_PATHS, and the
OpenAI/metadata settings.
"""

from __future__ import annotations

import os
from unittest import mock

import pytest

from publisher_v2.config.loader import (
    _load_captionfile_settings_from_env,
    _load_confirmation_settings_from_env,
    _load_content_settings_from_env,
    _load_email_server_from_env,
    _load_openai_settings_from_env,
    _load_publishers_from_env,
    _load_storage_paths_from_env,
    _resolve_path,
    _validate_path_no_traversal,
    log_config_source,
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

    @pytest.mark.parametrize(
        ("env_value", "expected"),
        [
            pytest.param(
                '{"sender": "bot@example.com"}',
                {"smtp_server": "smtp.gmail.com", "smtp_port": 587, "sender": "bot@example.com"},
                id="minimal-sender-only-uses-defaults",
            ),
            pytest.param(
                '{"smtp_server": "mail.custom.com", "smtp_port": 465, "sender": "noreply@custom.com"}',
                {"smtp_server": "mail.custom.com", "smtp_port": 465, "sender": "noreply@custom.com"},
                id="full",
            ),
        ],
    )
    def test_parses_config(self, env_value: str, expected: dict) -> None:
        """Parses EMAIL_SERVER; only ``sender`` is required, SMTP host/port default."""
        with mock.patch.dict(os.environ, {"EMAIL_SERVER": env_value}, clear=True):
            assert _load_email_server_from_env() == expected

    @pytest.mark.parametrize(
        ("env_value", "match"),
        [
            pytest.param('{"smtp_server": "mail.custom.com"}', "missing required field 'sender'", id="sender-missing"),
            pytest.param(
                '{"sender": "bot@example.com", "smtp_port": "not-a-number"}',
                "smtp_port must be an integer",
                id="smtp-port-not-integer",
            ),
            pytest.param("{not valid json}", "Invalid JSON in EMAIL_SERVER", id="invalid-json"),
        ],
    )
    def test_raises_on_invalid_config(self, env_value: str, match: str) -> None:
        """Raises ConfigurationError for a missing sender, a non-integer port, or invalid JSON."""
        with (
            mock.patch.dict(os.environ, {"EMAIL_SERVER": env_value}, clear=True),
            pytest.raises(ConfigurationError, match=match),
        ):
            _load_email_server_from_env()


# =============================================================================
# Story 04: Storage Paths Tests
# =============================================================================


class TestResolvePath:
    """Tests for _resolve_path function."""

    @pytest.mark.parametrize(
        ("base", "path", "expected"),
        [
            pytest.param("/dropbox/images", "archive", "/dropbox/images/archive", id="relative-joined-to-base"),
            pytest.param("/dropbox/images", "/other/archive", "/other/archive", id="absolute-returned-as-is"),
            pytest.param("/dropbox/images/", "archive", "/dropbox/images/archive", id="trailing-slash-in-base"),
        ],
    )
    def test_resolves_path(self, base: str, path: str, expected: str) -> None:
        """Relative paths resolve against base (trailing slash or not); absolute paths are kept."""
        assert _resolve_path(base, path) == expected


class TestValidatePathNoTraversal:
    """Tests for _validate_path_no_traversal function."""

    @pytest.mark.parametrize("path", ["/dropbox/images", "/dropbox/file.name.ext"])
    def test_allows_path_without_traversal(self, path: str) -> None:
        """Normal paths, including dots inside a filename, pass validation."""
        _validate_path_no_traversal(path, "root")  # No exception

    def test_rejects_path_with_double_dot(self):
        """Paths containing '..' are rejected."""
        with pytest.raises(ConfigurationError, match="contains '..' which is not allowed"):
            _validate_path_no_traversal("/dropbox/../etc", "root")


class TestLoadStoragePathsFromEnv:
    """Tests for _load_storage_paths_from_env function."""

    def test_returns_none_when_unset(self):
        """When STORAGE_PATHS is not set, returns None."""
        with mock.patch.dict(os.environ, {}, clear=True):
            os.environ.pop("STORAGE_PATHS", None)
            result = _load_storage_paths_from_env()
            assert result is None

    @pytest.mark.parametrize(
        ("env_value", "expected"),
        [
            pytest.param(
                '{"root": "/Dropbox/MyPhotos"}',
                {
                    "root": "/Dropbox/MyPhotos",
                    "archive": "/Dropbox/MyPhotos/archive",
                    "keep": "/Dropbox/MyPhotos/keep",
                    "remove": "/Dropbox/MyPhotos/reject",
                },
                id="minimal-root-only-uses-defaults",
            ),
            pytest.param(
                '{"root": "/Photos", "archive": "sent", "keep": "favorites", "remove": "trash"}',
                {"root": "/Photos", "archive": "/Photos/sent", "keep": "/Photos/favorites", "remove": "/Photos/trash"},
                id="full-relative-subpaths-joined-to-root",
            ),
            pytest.param(
                '{"root": "/Photos", "archive": "/Archive/sent"}',
                {"root": "/Photos", "archive": "/Archive/sent", "keep": "/Photos/keep", "remove": "/Photos/reject"},
                id="absolute-archive-kept",
            ),
            pytest.param(
                '{"root": "/photos", "keep": "/elsewhere/keep", "remove": "/elsewhere/reject"}',
                {
                    "root": "/photos",
                    "archive": "/photos/archive",
                    "keep": "/elsewhere/keep",
                    "remove": "/elsewhere/reject",
                },
                id="absolute-keep-remove-kept",
            ),
        ],
    )
    def test_parses_config(self, env_value: str, expected: dict) -> None:
        """Parses STORAGE_PATHS: only ``root`` is required; relative subpaths join it, absolute ones are kept."""
        with mock.patch.dict(os.environ, {"STORAGE_PATHS": env_value}, clear=True):
            assert _load_storage_paths_from_env() == expected

    @pytest.mark.parametrize(
        ("env_value", "match"),
        [
            pytest.param('{"archive": "sent"}', "missing required field 'root'", id="root-missing"),
            pytest.param('{"root": "relative/path"}', "must be an absolute path", id="root-not-absolute"),
            pytest.param('{"root": "/Dropbox/../etc"}', "contains '..' which is not allowed", id="root-traversal"),
            pytest.param(
                '{"root": "/Dropbox", "archive": "../etc"}',
                "contains '..' which is not allowed",
                id="archive-traversal",
            ),
            pytest.param(
                '{"root": "/Photos", "keep": "../escape"}', "contains '..' which is not allowed", id="keep-traversal"
            ),
            pytest.param(
                '{"root": "/Photos", "keep": "sub/../dir"}',
                "contains '..' which is not allowed",
                id="keep-inner-traversal",
            ),
        ],
    )
    def test_raises_on_invalid_config(self, env_value: str, match: str) -> None:
        """Raises ConfigurationError for a missing/relative root or a '..' in any path."""
        with (
            mock.patch.dict(os.environ, {"STORAGE_PATHS": env_value}, clear=True),
            pytest.raises(ConfigurationError, match=match),
        ):
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
        env_value = (
            '{"confirmation_to_sender": false, "confirmation_tags_count": 10, "confirmation_tags_nature": "nouns only"}'
        )
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


class TestLoadPublishersFromEnv:
    """Tests for _load_publishers_from_env function."""

    def test_telegram_publisher(self):
        """Parses Telegram publisher from PUBLISHERS."""
        entries = [{"type": "telegram", "channel_id": "@test_channel"}]
        with mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "test-bot-token"}, clear=True):
            telegram, instagram, email, platforms = _load_publishers_from_env(entries, None)
            assert telegram is not None
            assert telegram.bot_token == "test-bot-token"
            assert telegram.channel_id == "@test_channel"
            assert platforms.telegram_enabled is True
            assert instagram is None
            assert email is None

    @pytest.mark.parametrize(
        ("entry", "env", "match"),
        [
            pytest.param(
                {"type": "telegram", "channel_id": "@test_channel"}, {}, "TELEGRAM_BOT_TOKEN required", id="tg-token"
            ),
            pytest.param(
                {"type": "telegram"},
                {"TELEGRAM_BOT_TOKEN": "test"},
                "missing required field 'channel_id'",
                id="tg-channel-id",
            ),
            pytest.param(
                {"type": "fetlife", "recipient": "user@fetlife.com"}, {}, "EMAIL_PASSWORD required", id="fetlife-pass"
            ),
            pytest.param(
                {"type": "fetlife"},
                {"EMAIL_PASSWORD": "secret"},
                "missing required field 'recipient'",
                id="fetlife-recipient",
            ),
            pytest.param(
                {"type": "instagram", "username": "photo_account"}, {}, "INSTA_PASSWORD required", id="insta-pass"
            ),
            pytest.param(
                {"type": "instagram"},
                {"INSTA_PASSWORD": "secret"},
                "missing required field 'username'",
                id="insta-username",
            ),
        ],
    )
    def test_publisher_missing_field_raises(self, entry: dict, env: dict, match: str) -> None:
        """Raises ConfigurationError when a publisher's secret env var or required PUBLISHERS field is missing."""
        with mock.patch.dict(os.environ, env, clear=True), pytest.raises(ConfigurationError, match=match):
            _load_publishers_from_env([entry], None)

    def test_fetlife_publisher_with_email_server(self):
        """Parses FetLife publisher using EMAIL_SERVER settings."""
        entries = [{"type": "fetlife", "recipient": "user@fetlife.com", "caption_target": "body"}]
        email_server = {"smtp_server": "smtp.env.com", "smtp_port": 587, "sender": "sender@env.com"}
        with mock.patch.dict(os.environ, {"EMAIL_PASSWORD": "secret123"}, clear=True):
            telegram, instagram, email, platforms = _load_publishers_from_env(entries, email_server)
            assert email is not None
            assert email.smtp_server == "smtp.env.com"
            assert email.smtp_port == 587
            assert email.sender == "sender@env.com"
            assert email.recipient == "user@fetlife.com"
            assert email.caption_target == "body"
            assert platforms.email_enabled is True

    def test_fetlife_publisher_fallback_to_flat_env(self):
        """#97 stage 4: without EMAIL_SERVER, SMTP settings fall back to flat env vars (INI removed)."""
        entries = [{"type": "fetlife", "recipient": "user@fetlife.com"}]
        env = {"EMAIL_PASSWORD": "secret123", "SMTP_SERVER": "smtp.flat.com", "SMTP_PORT": "25"}
        with mock.patch.dict(os.environ, env, clear=True):
            telegram, instagram, email, platforms = _load_publishers_from_env(entries, None)
            assert email is not None
            assert email.smtp_server == "smtp.flat.com"
            assert email.smtp_port == 25
            assert email.sender == ""

    def test_instagram_publisher(self):
        """Parses Instagram publisher from PUBLISHERS."""
        entries = [{"type": "instagram", "username": "photo_account"}]
        with mock.patch.dict(os.environ, {"INSTA_PASSWORD": "insta-secret"}, clear=True):
            telegram, instagram, email, platforms = _load_publishers_from_env(entries, None)
            assert instagram is not None
            assert instagram.username == "photo_account"
            assert instagram.password == "insta-secret"
            assert platforms.instagram_enabled is True

    def test_multiple_publishers(self):
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
            telegram, instagram, email, platforms = _load_publishers_from_env(entries, email_server)
            assert telegram is not None
            assert email is not None
            assert instagram is None
            assert platforms.telegram_enabled is True
            assert platforms.email_enabled is True
            assert platforms.instagram_enabled is False

    def test_duplicate_publisher_type_raises(self):
        """Raises ConfigurationError when duplicate publisher types exist."""
        entries = [
            {"type": "telegram", "channel_id": "@channel1"},
            {"type": "telegram", "channel_id": "@channel2"},
        ]
        with (
            mock.patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "token"}, clear=True),
            pytest.raises(ConfigurationError, match="Duplicate publisher type 'telegram'"),
        ):
            _load_publishers_from_env(entries, None)

    def test_unknown_publisher_type_logs_warning(self, caplog):
        """Unknown publisher types are skipped with a warning."""
        entries = [{"type": "unknown_platform", "channel": "test"}]
        with mock.patch.dict(os.environ, {}, clear=True):
            telegram, instagram, email, platforms = _load_publishers_from_env(entries, None)
            assert telegram is None
            assert instagram is None
            assert email is None
            assert "Unknown publisher type 'unknown_platform'" in caplog.text

    def test_empty_publishers_list(self):
        """Empty PUBLISHERS list results in all publishers disabled."""
        entries = []
        with mock.patch.dict(os.environ, {}, clear=True):
            telegram, instagram, email, platforms = _load_publishers_from_env(entries, None)
            assert telegram is None
            assert instagram is None
            assert email is None
            assert platforms.telegram_enabled is False
            assert platforms.instagram_enabled is False
            assert platforms.email_enabled is False

    def test_fetlife_with_confirmation_settings_from_env(self):
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
            telegram, instagram, email, platforms = _load_publishers_from_env(entries, email_server)
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

    def test_ini_fallback_source_no_longer_special_cased(self, caplog):
        """#97 stage 4: INI removed — log_config_source always logs env_vars."""
        import logging

        caplog.set_level(logging.INFO)
        log_config_source("ini_fallback", publishers_count=1, storage_source="STORAGE_PATHS")
        assert "Config source: env_vars" in caplog.text
        assert "ini_fallback" not in caplog.text
