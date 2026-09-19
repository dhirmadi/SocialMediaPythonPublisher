"""Loader tests — env-only configuration (#97 stage 4: INI support removed)."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from publisher_v2.config.loader import load_application_config
from publisher_v2.core.exceptions import ConfigurationError


@pytest.fixture
def valid_env_vars(monkeypatch):
    """Baseline env-only configuration: Dropbox storage + telegram publisher."""
    monkeypatch.setattr("publisher_v2.config.loader.load_dotenv", lambda *args, **kwargs: None)
    for key in (
        "EMAIL_SERVER",
        "CONTENT_SETTINGS",
        "CAPTIONFILE_SETTINGS",
        "CONFIRMATION_SETTINGS",
        "STORAGE_PROVIDER",
        "EMAIL_PASSWORD",
        "INSTA_PASSWORD",
    ):
        monkeypatch.delenv(key, raising=False)

    monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
    monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test123")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")

    monkeypatch.setenv("STORAGE_PATHS", json.dumps({"root": "/Photos", "archive": "archive"}))
    monkeypatch.setenv("PUBLISHERS", json.dumps([{"type": "telegram", "channel_id": "@testchannel"}]))
    monkeypatch.setenv("OPENAI_SETTINGS", json.dumps({"vision_model": "gpt-4o", "caption_model": "gpt-4o-mini"}))


def test_load_valid_config(valid_env_vars):
    """Env-only configuration loads end to end."""
    config = load_application_config()

    assert config.dropbox.app_key == "test_key"
    assert config.dropbox.image_folder == "/Photos"
    assert config.dropbox.archive_folder == "/Photos/archive"
    assert config.openai.api_key == "sk-test123"
    assert config.openai.vision_model == "gpt-4o"
    assert config.openai.caption_model == "gpt-4o-mini"
    assert config.platforms.telegram_enabled is True
    assert config.platforms.instagram_enabled is False
    assert config.platforms.email_enabled is False
    assert config.telegram is not None
    assert config.telegram.bot_token == "123:ABC"
    assert config.content.hashtag_string == ""
    assert config.content.archive is True
    assert config.content.debug is False


def test_ini_file_is_ignored(valid_env_vars, tmp_path, caplog):
    """#97 stage 4: a config_file_path is accepted for CLI compat but its contents are ignored."""
    import logging

    ini = tmp_path / "test.ini"
    ini.write_text("[Dropbox]\nimage_folder = /FromIni\n")

    with caplog.at_level(logging.WARNING):
        config = load_application_config(str(ini))

    # Values come from env, never from the INI file.
    assert config.dropbox.image_folder == "/Photos"
    assert any("INI configuration was removed" in rec.getMessage() for rec in caplog.records)


def test_missing_required_env_vars_raises(valid_env_vars, monkeypatch):
    """#97 stage 4: without the JSON env vars there is no fallback — hard error."""
    monkeypatch.delenv("STORAGE_PATHS", raising=False)
    monkeypatch.delenv("PUBLISHERS", raising=False)

    with pytest.raises(ConfigurationError, match="STORAGE_PATHS, PUBLISHERS"):
        load_application_config()


def test_load_config_missing_dropbox_env(valid_env_vars, monkeypatch):
    """Missing DROPBOX_APP_KEY raises ConfigurationError."""
    monkeypatch.delenv("DROPBOX_APP_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="Missing required environment variable"):
        load_application_config()


def test_load_config_missing_openai_key(valid_env_vars, monkeypatch):
    """Missing OPENAI_API_KEY raises ConfigurationError."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="Missing required environment variable"):
        load_application_config()


def test_load_config_invalid_storage_root(valid_env_vars, monkeypatch):
    """Relative STORAGE_PATHS.root raises."""
    monkeypatch.setenv("STORAGE_PATHS", json.dumps({"root": "Photos"}))

    with pytest.raises((ValidationError, ConfigurationError)):
        load_application_config()


def test_load_config_default_models(valid_env_vars, monkeypatch):
    """Empty OPENAI_SETTINGS uses default models."""
    monkeypatch.setenv("OPENAI_SETTINGS", "{}")

    config = load_application_config()
    assert config.openai.vision_model == "gpt-4o"
    assert config.openai.caption_model == "gpt-4o-mini"


def test_load_config_with_email_publisher(valid_env_vars, monkeypatch):
    """fetlife publisher + EMAIL_SERVER builds EmailConfig."""
    monkeypatch.setenv("EMAIL_PASSWORD", "test_pass")
    monkeypatch.setenv(
        "EMAIL_SERVER",
        json.dumps({"sender": "test@example.com", "smtp_server": "smtp.gmail.com", "smtp_port": 587}),
    )
    monkeypatch.setenv("PUBLISHERS", json.dumps([{"type": "fetlife", "recipient": "recipient@example.com"}]))

    config = load_application_config()

    assert config.platforms.email_enabled is True
    assert config.email is not None
    assert config.email.sender == "test@example.com"
    assert config.email.recipient == "recipient@example.com"
    assert config.email.password == "test_pass"
    assert config.email.smtp_server == "smtp.gmail.com"
    assert config.email.smtp_port == 587


def test_load_config_with_instagram_publisher(valid_env_vars, monkeypatch):
    """instagram publisher entry builds InstagramConfig."""
    monkeypatch.setenv("INSTA_PASSWORD", "insta_pass")
    monkeypatch.setenv("PUBLISHERS", json.dumps([{"type": "instagram", "username": "testuser"}]))

    config = load_application_config()

    assert config.platforms.instagram_enabled is True
    assert config.instagram is not None
    assert config.instagram.username == "testuser"
    assert config.instagram.password == "insta_pass"
    # #133: no fixed relative "instasession.json"; None lets the session store use $XDG_CACHE_HOME.
    assert config.instagram.session_file is None


def test_load_config_captionfile_extended_metadata(valid_env_vars, monkeypatch):
    monkeypatch.setenv(
        "CAPTIONFILE_SETTINGS", json.dumps({"extended_metadata_enabled": True, "artist_alias": "TestArtist"})
    )

    config = load_application_config()
    assert config.captionfile.extended_metadata_enabled is True
    assert config.captionfile.artist_alias == "TestArtist"


def test_load_config_captionfile_defaults(valid_env_vars):
    """CAPTIONFILE_SETTINGS unset: defaults."""
    config = load_application_config()
    assert config.captionfile.extended_metadata_enabled is False
    assert config.captionfile.artist_alias is None


def test_load_config_content_defaults(valid_env_vars):
    """#97 stage 4: CONTENT_SETTINGS unset falls back to schema defaults (no INI)."""
    config = load_application_config()
    assert config.content.hashtag_string == ""
    assert config.content.archive is True
    assert config.content.debug is False


def test_load_config_sd_caption_flags(valid_env_vars, monkeypatch):
    """SD caption flags come from OPENAI_SETTINGS."""
    monkeypatch.setenv(
        "OPENAI_SETTINGS",
        json.dumps(
            {
                "vision_model": "gpt-4o",
                "sd_caption_enabled": True,
                "sd_caption_single_call_enabled": False,
                "sd_caption_model": "gpt-4o-mini",
                "sd_caption_system_prompt": "Custom SD prompt",
                "sd_caption_role_prompt": "Custom role",
            }
        ),
    )

    config = load_application_config()

    assert config.openai.sd_caption_enabled is True
    assert config.openai.sd_caption_single_call_enabled is False
    assert config.openai.sd_caption_model == "gpt-4o-mini"
    assert config.openai.sd_caption_system_prompt == "Custom SD prompt"
    assert config.openai.sd_caption_role_prompt == "Custom role"


def test_load_config_with_env_file(valid_env_vars, tmp_path, monkeypatch):
    """Explicit .env file path is loaded (secrets can come from it)."""
    # Re-enable dotenv loading for this test only.
    from dotenv import load_dotenv as real_load_dotenv

    monkeypatch.setattr("publisher_v2.config.loader.load_dotenv", real_load_dotenv)
    monkeypatch.delenv("DROPBOX_APP_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    env_file = tmp_path / ".env"
    env_file.write_text("DROPBOX_APP_KEY=env_key\nOPENAI_API_KEY=sk-envkey\n")

    config = load_application_config(env_path=str(env_file))

    assert config.dropbox.app_key == "env_key"
    assert config.openai.api_key == "sk-envkey"


def test_load_config_archive_folder_default(valid_env_vars, monkeypatch):
    """archive defaults to <root>/archive when omitted from STORAGE_PATHS."""
    monkeypatch.setenv("STORAGE_PATHS", json.dumps({"root": "/Photos"}))

    config = load_application_config()
    assert config.dropbox.archive_folder == "/Photos/archive"


def test_feature_toggles_default_enabled(valid_env_vars, monkeypatch):
    monkeypatch.delenv("FEATURE_ANALYZE_CAPTION", raising=False)
    monkeypatch.delenv("FEATURE_PUBLISH", raising=False)

    cfg = load_application_config()
    assert cfg.features.analyze_caption_enabled is True
    assert cfg.features.publish_enabled is True


def test_feature_toggles_can_be_disabled(valid_env_vars, monkeypatch):
    monkeypatch.setenv("FEATURE_ANALYZE_CAPTION", "false")
    monkeypatch.setenv("FEATURE_PUBLISH", "0")

    cfg = load_application_config()
    assert cfg.features.analyze_caption_enabled is False
    assert cfg.features.publish_enabled is False


def test_feature_toggles_invalid_value_raises(valid_env_vars, monkeypatch):
    monkeypatch.setenv("FEATURE_ANALYZE_CAPTION", "maybe")

    with pytest.raises(ConfigurationError):
        load_application_config()


# ---------------------------------------------------------------------------
# #97 stage 1: phantom / mismatched feature flags
# (rebased onto stage 4's env-only fixtures — INI support is gone)
# ---------------------------------------------------------------------------


def test_feature_delete_env_sets_delete_enabled(valid_env_vars, monkeypatch):
    """FEATURE_DELETE=true is parsed by the loader (was a phantom flag)."""
    monkeypatch.setenv("FEATURE_DELETE", "true")

    cfg = load_application_config()
    assert cfg.features.delete_enabled is True


def test_feature_delete_defaults_false(valid_env_vars, monkeypatch):
    monkeypatch.delenv("FEATURE_DELETE", raising=False)

    cfg = load_application_config()
    assert cfg.features.delete_enabled is False


def test_feature_auto_view_documented_name_works(valid_env_vars, monkeypatch):
    """FEATURE_AUTO_VIEW (the documented name) is honored."""
    monkeypatch.delenv("AUTO_VIEW", raising=False)
    monkeypatch.setenv("FEATURE_AUTO_VIEW", "true")

    cfg = load_application_config()
    assert cfg.features.auto_view_enabled is True


def test_auto_view_legacy_alias_works_with_deprecation_log(valid_env_vars, monkeypatch, caplog):
    """AUTO_VIEW still works as a deprecated alias and logs a deprecation warning."""
    import logging

    monkeypatch.delenv("FEATURE_AUTO_VIEW", raising=False)
    monkeypatch.setenv("AUTO_VIEW", "true")
    # reset the log-once guard so this test is order-independent
    import publisher_v2.config.loader as loader_mod

    monkeypatch.setattr(loader_mod, "_auto_view_alias_warned", False, raising=False)

    with caplog.at_level(logging.WARNING):
        cfg = load_application_config()
    assert cfg.features.auto_view_enabled is True
    assert any("AUTO_VIEW" in rec.getMessage() and "deprecat" in rec.getMessage().lower() for rec in caplog.records)


def test_feature_auto_view_takes_precedence_over_alias(valid_env_vars, monkeypatch):
    monkeypatch.setenv("FEATURE_AUTO_VIEW", "false")
    monkeypatch.setenv("AUTO_VIEW", "true")

    cfg = load_application_config()
    assert cfg.features.auto_view_enabled is False


def test_library_enabled_populated_by_loader(valid_env_vars, monkeypatch):
    """FEATURE_LIBRARY env resolves into features.library_enabled (was resolved ad hoc)."""
    monkeypatch.setenv("FEATURE_LIBRARY", "true")

    cfg = load_application_config()
    assert cfg.features.library_enabled is True


def test_library_enabled_defaults_false_without_managed(valid_env_vars, monkeypatch):
    """Dropbox-only instance without FEATURE_LIBRARY: library stays off."""
    monkeypatch.delenv("FEATURE_LIBRARY", raising=False)

    cfg = load_application_config()
    assert cfg.features.library_enabled is False


# --- #131: voice matching defaults on through the real loader when a profile exists ---


def test_voice_profile_without_flag_enables_voice_matching(valid_env_vars, monkeypatch):
    monkeypatch.delenv("FEATURE_VOICE_MATCHING", raising=False)
    monkeypatch.setenv("CONTENT_SETTINGS", json.dumps({"voice_profile": ["my own caption, my own voice"]}))
    cfg = load_application_config()
    assert cfg.content.voice_profile == ["my own caption, my own voice"]
    assert cfg.features.voice_matching_enabled is True


def test_voice_profile_with_explicit_false_keeps_voice_matching_off(valid_env_vars, monkeypatch):
    monkeypatch.setenv("FEATURE_VOICE_MATCHING", "false")
    monkeypatch.setenv("CONTENT_SETTINGS", json.dumps({"voice_profile": ["my own caption, my own voice"]}))
    cfg = load_application_config()
    assert cfg.features.voice_matching_enabled is False


def test_no_voice_profile_and_no_flag_keeps_voice_matching_off(valid_env_vars, monkeypatch):
    monkeypatch.delenv("FEATURE_VOICE_MATCHING", raising=False)
    cfg = load_application_config()
    assert cfg.features.voice_matching_enabled is False
