from __future__ import annotations

import pytest
from pathlib import Path
from pydantic import ValidationError

from publisher_v2.config.loader import load_application_config
from publisher_v2.core.exceptions import ConfigurationError


@pytest.fixture
def valid_ini_content():
    """Valid INI configuration for testing."""
    return """[Dropbox]
image_folder = /Photos
archive = archive

[openAI]
vision_model = gpt-4o
caption_model = gpt-4o-mini
system_prompt = Test prompt
role_prompt = Caption:

[Content]
hashtag_string = #test
archive = true
debug = false
telegram = true
instagram = false
fetlife = false

[CaptionFile]
extended_metadata_enabled = false
"""


@pytest.fixture
def valid_env_vars(monkeypatch):
    """Set up valid environment variables and clear existing ones."""
    # Clear any existing env vars that might interfere
    monkeypatch.delenv("DROPBOX_APP_KEY", raising=False)
    monkeypatch.delenv("DROPBOX_APP_SECRET", raising=False)
    monkeypatch.delenv("DROPBOX_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHANNEL_ID", raising=False)
    
    # Set test values
    monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
    monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test123")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:ABC")
    monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@testchannel")


def test_load_valid_config(tmp_path, valid_ini_content, valid_env_vars):
    """Test loading a valid configuration file."""
    config_file = tmp_path / "test.ini"
    config_file.write_text(valid_ini_content)
    
    config = load_application_config(str(config_file))
    
    assert config.dropbox.app_key == "test_key"
    assert config.dropbox.image_folder == "/Photos"
    assert config.dropbox.archive_folder == "archive"
    assert config.openai.api_key == "sk-test123"
    assert config.openai.vision_model == "gpt-4o"
    assert config.openai.caption_model == "gpt-4o-mini"
    assert config.platforms.telegram_enabled is True
    assert config.platforms.instagram_enabled is False
    assert config.platforms.email_enabled is False
    assert config.telegram is not None
    assert config.telegram.bot_token == "123:ABC"
    # Note: hashtag_string with # is treated as comment due to inline_comment_prefixes
    # This matches actual config loader behavior
    assert config.content.hashtag_string == ""
    assert config.content.archive is True
    assert config.content.debug is False


def test_load_config_missing_file():
    """Test that missing config file raises ConfigurationError."""
    with pytest.raises(ConfigurationError, match="Config file not found"):
        load_application_config("/nonexistent/path.ini")


def test_load_config_missing_dropbox_env(tmp_path, valid_ini_content, monkeypatch):
    """Test that missing DROPBOX_APP_KEY raises ConfigurationError."""
    config_file = tmp_path / "test.ini"
    config_file.write_text(valid_ini_content)
    
    # Create empty .env file to prevent loading workspace .env
    empty_env = tmp_path / ".env"
    empty_env.write_text("")
    
    # Clear all env vars first
    monkeypatch.delenv("DROPBOX_APP_KEY", raising=False)
    monkeypatch.delenv("DROPBOX_APP_SECRET", raising=False)
    monkeypatch.delenv("DROPBOX_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    
    # Set only some env vars, missing DROPBOX_APP_KEY
    monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
    monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test123")
    
    with pytest.raises(ConfigurationError, match="Missing required environment variable"):
        load_application_config(str(config_file), env_path=str(empty_env))


def test_load_config_missing_openai_key(tmp_path, valid_ini_content, monkeypatch):
    """Test that missing OPENAI_API_KEY raises ConfigurationError."""
    config_file = tmp_path / "test.ini"
    config_file.write_text(valid_ini_content)
    
    # Create empty .env file to prevent loading workspace .env
    empty_env = tmp_path / ".env"
    empty_env.write_text("")
    
    # Clear all env vars first
    monkeypatch.delenv("DROPBOX_APP_KEY", raising=False)
    monkeypatch.delenv("DROPBOX_APP_SECRET", raising=False)
    monkeypatch.delenv("DROPBOX_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    
    # Set Dropbox vars but not OpenAI
    monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
    monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
    
    with pytest.raises(ConfigurationError, match="Missing required environment variable"):
        load_application_config(str(config_file), env_path=str(empty_env))


def test_load_config_invalid_dropbox_folder(tmp_path, valid_env_vars):
    """Test that invalid image_folder (no leading slash) raises ValidationError."""
    invalid_ini = """[Dropbox]
image_folder = Photos
archive = archive

[openAI]
vision_model = gpt-4o

[Content]
archive = true
debug = false
"""
    config_file = tmp_path / "test.ini"
    config_file.write_text(invalid_ini)
    
    with pytest.raises((ValidationError, ConfigurationError)):
        load_application_config(str(config_file))


def test_load_config_legacy_model_field(tmp_path, valid_env_vars):
    """Test backward compatibility with legacy 'model' field."""
    legacy_ini = """[Dropbox]
image_folder = /Photos

[openAI]
model = gpt-4o

[Content]
archive = true
debug = false
"""
    config_file = tmp_path / "test.ini"
    config_file.write_text(legacy_ini)
    
    config = load_application_config(str(config_file))
    
    # Should use legacy model for both vision and caption
    assert config.openai.vision_model == "gpt-4o"
    assert config.openai.caption_model == "gpt-4o"
    assert config.openai.model == "gpt-4o"


def test_load_config_separate_models_override_legacy(tmp_path, valid_env_vars):
    """Test that explicit vision/caption models override legacy model."""
    mixed_ini = """[Dropbox]
image_folder = /Photos

[openAI]
model = gpt-4o
vision_model = gpt-4o-mini
caption_model = gpt-3.5-turbo

[Content]
archive = true
debug = false
"""
    config_file = tmp_path / "test.ini"
    config_file.write_text(mixed_ini)
    
    config = load_application_config(str(config_file))
    
    # Explicit models should take precedence
    assert config.openai.vision_model == "gpt-4o-mini"
    assert config.openai.caption_model == "gpt-3.5-turbo"


def test_load_config_default_models(tmp_path, valid_env_vars):
    """Test that default models are used when none specified."""
    minimal_ini = """[Dropbox]
image_folder = /Photos

[openAI]

[Content]
archive = true
debug = false
"""
    config_file = tmp_path / "test.ini"
    config_file.write_text(minimal_ini)
    
    config = load_application_config(str(config_file))
    
    # Should use defaults
    assert config.openai.vision_model == "gpt-4o"
    assert config.openai.caption_model == "gpt-4o-mini"


def test_load_config_with_email_section(tmp_path, valid_env_vars, monkeypatch):
    """Test loading config with Email section enabled."""
    email_ini = """[Dropbox]
image_folder = /Photos

[openAI]
vision_model = gpt-4o

[Content]
archive = true
debug = false
fetlife = true

[Email]
sender = test@example.com
recipient = recipient@example.com
smtp_server = smtp.gmail.com
smtp_port = 587
confirmation_to_sender = true
confirmation_tags_count = 5
caption_target = subject
subject_mode = normal
"""
    config_file = tmp_path / "test.ini"
    config_file.write_text(email_ini)
    
    monkeypatch.setenv("EMAIL_PASSWORD", "test_pass")
    
    config = load_application_config(str(config_file))
    
    assert config.platforms.email_enabled is True
    assert config.email is not None
    assert config.email.sender == "test@example.com"
    assert config.email.recipient == "recipient@example.com"
    assert config.email.password == "test_pass"
    assert config.email.smtp_server == "smtp.gmail.com"
    assert config.email.smtp_port == 587


def test_load_config_with_instagram_section(tmp_path, valid_env_vars, monkeypatch):
    """Test loading config with Instagram section enabled."""
    instagram_ini = """[Dropbox]
image_folder = /Photos

[openAI]
vision_model = gpt-4o

[Content]
archive = true
debug = false
instagram = true

[Instagram]
name = testuser
"""
    config_file = tmp_path / "test.ini"
    config_file.write_text(instagram_ini)
    
    monkeypatch.setenv("INSTA_PASSWORD", "insta_pass")
    
    config = load_application_config(str(config_file))
    
    assert config.platforms.instagram_enabled is True
    assert config.instagram is not None
    assert config.instagram.username == "testuser"
    assert config.instagram.password == "insta_pass"
    assert config.instagram.session_file == "instasession.json"


def test_load_config_captionfile_extended_metadata(tmp_path, valid_env_vars):
    """Test loading CaptionFile config with extended_metadata_enabled."""
    captionfile_ini = """[Dropbox]
image_folder = /Photos

[openAI]
vision_model = gpt-4o

[Content]
archive = true
debug = false

[CaptionFile]
extended_metadata_enabled = true
artist_alias = TestArtist
"""
    config_file = tmp_path / "test.ini"
    config_file.write_text(captionfile_ini)
    
    config = load_application_config(str(config_file))
    
    assert config.captionfile.extended_metadata_enabled is True
    assert config.captionfile.artist_alias == "TestArtist"


def test_load_config_captionfile_defaults(tmp_path, valid_env_vars):
    """Test CaptionFile config defaults when section missing."""
    minimal_ini = """[Dropbox]
image_folder = /Photos

[openAI]
vision_model = gpt-4o

[Content]
archive = true
debug = false
"""
    config_file = tmp_path / "test.ini"
    config_file.write_text(minimal_ini)
    
    config = load_application_config(str(config_file))
    
    # Should use defaults
    assert config.captionfile.extended_metadata_enabled is False
    assert config.captionfile.artist_alias is None


def test_load_config_sd_caption_flags(tmp_path, valid_env_vars):
    """Test loading SD caption feature flags from OpenAI section."""
    sd_ini = """[Dropbox]
image_folder = /Photos

[openAI]
vision_model = gpt-4o
sd_caption_enabled = true
sd_caption_single_call_enabled = false
sd_caption_model = gpt-4o-mini
sd_caption_system_prompt = Custom SD prompt
sd_caption_role_prompt = Custom role

[Content]
archive = true
debug = false
"""
    config_file = tmp_path / "test.ini"
    config_file.write_text(sd_ini)
    
    config = load_application_config(str(config_file))
    
    assert config.openai.sd_caption_enabled is True
    assert config.openai.sd_caption_single_call_enabled is False
    assert config.openai.sd_caption_model == "gpt-4o-mini"
    assert config.openai.sd_caption_system_prompt == "Custom SD prompt"
    assert config.openai.sd_caption_role_prompt == "Custom role"


def test_load_config_with_env_file(tmp_path, monkeypatch):
    """Test loading config with explicit .env file path."""
    # Clear existing env vars
    monkeypatch.delenv("DROPBOX_APP_KEY", raising=False)
    monkeypatch.delenv("DROPBOX_APP_SECRET", raising=False)
    monkeypatch.delenv("DROPBOX_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    
    config_ini = """[Dropbox]
image_folder = /Photos

[openAI]
vision_model = gpt-4o

[Content]
archive = true
debug = false
"""
    config_file = tmp_path / "test.ini"
    config_file.write_text(config_ini)
    
    env_file = tmp_path / ".env"
    env_file.write_text("""DROPBOX_APP_KEY=env_key
DROPBOX_APP_SECRET=env_secret
DROPBOX_REFRESH_TOKEN=env_refresh
OPENAI_API_KEY=sk-envkey
""")
    
    config = load_application_config(str(config_file), env_path=str(env_file))
    
    assert config.dropbox.app_key == "env_key"
    assert config.openai.api_key == "sk-envkey"


def test_load_config_archive_folder_fallback(tmp_path, valid_env_vars):
    """Test that archive_folder fallback works when not specified."""
    minimal_ini = """[Dropbox]
image_folder = /Photos

[openAI]
vision_model = gpt-4o

[Content]
archive = true
debug = false
"""
    config_file = tmp_path / "test.ini"
    config_file.write_text(minimal_ini)
    
    config = load_application_config(str(config_file))
    
    # Should use default fallback
    assert config.dropbox.archive_folder == "archive"


def test_load_config_malformed_ini(tmp_path, valid_env_vars):
    """Test that malformed INI raises ConfigurationError."""
    malformed_ini = """[Dropbox]
image_folder = /Photos
[openAI
this section header is malformed
"""
    config_file = tmp_path / "test.ini"
    config_file.write_text(malformed_ini)
    
    # ConfigParser will raise ParsingError for malformed section headers
    with pytest.raises((ConfigurationError, Exception)):
        load_application_config(str(config_file))


def test_feature_toggles_default_enabled(tmp_path, valid_ini_content, valid_env_vars, monkeypatch):
    """Feature toggles default to enabled when env vars not set."""
    # Ensure .env contents do not interfere with this test; we want a clean env-only view.
    monkeypatch.setattr("publisher_v2.config.loader.load_dotenv", lambda *args, **kwargs: None)
    monkeypatch.delenv("FEATURE_ANALYZE_CAPTION", raising=False)
    monkeypatch.delenv("FEATURE_PUBLISH", raising=False)
    config_file = tmp_path / "test.ini"
    config_file.write_text(valid_ini_content)

    cfg = load_application_config(str(config_file))
    assert cfg.features.analyze_caption_enabled is True
    assert cfg.features.publish_enabled is True


def test_feature_toggles_can_be_disabled(tmp_path, valid_ini_content, valid_env_vars, monkeypatch):
    """Feature toggles honor false-ish values."""
    monkeypatch.setenv("FEATURE_ANALYZE_CAPTION", "false")
    monkeypatch.setenv("FEATURE_PUBLISH", "0")
    config_file = tmp_path / "test.ini"
    config_file.write_text(valid_ini_content)

    cfg = load_application_config(str(config_file))
    assert cfg.features.analyze_caption_enabled is False
    assert cfg.features.publish_enabled is False


def test_feature_toggles_invalid_value_raises(tmp_path, valid_ini_content, valid_env_vars, monkeypatch):
    """Invalid toggle values raise ConfigurationError."""
    monkeypatch.setenv("FEATURE_ANALYZE_CAPTION", "maybe")
    config_file = tmp_path / "test.ini"
    config_file.write_text(valid_ini_content)

    with pytest.raises(ConfigurationError):
        load_application_config(str(config_file))

