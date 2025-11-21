from __future__ import annotations

import configparser
import os
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    CaptionFileConfig,
    DropboxConfig,
    FeaturesConfig,
    EmailConfig,
    InstagramConfig,
    OpenAIConfig,
    PlatformsConfig,
    TelegramConfig,
    WebConfig,
)
from publisher_v2.core.exceptions import ConfigurationError


def parse_bool_env(value: str | None, default: bool = True, *, var_name: str | None = None) -> bool:
    """
    Parse common truthy/falsey strings for environment variables.

    Raises ConfigurationError for invalid values.
    """
    if value is None:
        return default

    normalized = value.strip().lower()
    truthy = {"1", "true", "yes", "on"}
    falsey = {"0", "false", "no", "off"}
    if normalized in truthy:
        return True
    if normalized in falsey:
        return False
    name = var_name or "environment variable"
    raise ConfigurationError(f"Invalid boolean value '{value}' for {name}; expected one of {truthy | falsey}")


def load_application_config(config_file_path: str, env_path: str | None = None) -> ApplicationConfig:
    """
    Load and validate application configuration from INI and .env.
    """
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()

    # Configure parser to handle inline comments (e.g., "value ; comment")
    cp = configparser.ConfigParser(inline_comment_prefixes=(';', '#'))
    if not os.path.exists(config_file_path):
        raise ConfigurationError(f"Config file not found: {config_file_path}")
    cp.read(config_file_path)

    try:
        dropbox = DropboxConfig(
            app_key=os.environ["DROPBOX_APP_KEY"],
            app_secret=os.environ["DROPBOX_APP_SECRET"],
            refresh_token=os.environ["DROPBOX_REFRESH_TOKEN"],
            image_folder=cp.get("Dropbox", "image_folder"),
            archive_folder=cp.get("Dropbox", "archive", fallback="archive"),
        )
        # Load OpenAI config with support for both legacy 'model' and new separate models
        vision_model = cp.get("openAI", "vision_model", fallback=None)
        caption_model = cp.get("openAI", "caption_model", fallback=None)
        legacy_model = cp.get("openAI", "model", fallback=None)
        # SD caption feature flags and overrides
        sd_caption_enabled = cp.getboolean("openAI", "sd_caption_enabled", fallback=True)
        sd_caption_single_call_enabled = cp.getboolean("openAI", "sd_caption_single_call_enabled", fallback=True)
        sd_caption_model = cp.get("openAI", "sd_caption_model", fallback=None)
        sd_caption_system_prompt = cp.get("openAI", "sd_caption_system_prompt", fallback=None)
        sd_caption_role_prompt = cp.get("openAI", "sd_caption_role_prompt", fallback=None)
        
        # Backward compatibility: if only 'model' is specified, use it for both
        if legacy_model and not vision_model:
            vision_model = legacy_model
        if legacy_model and not caption_model:
            caption_model = legacy_model
        
        # Use defaults if nothing specified
        if not vision_model:
            vision_model = "gpt-4o"
        if not caption_model:
            caption_model = "gpt-4o-mini"
        
        openai_cfg = OpenAIConfig(
            api_key=os.environ["OPENAI_API_KEY"],
            vision_model=vision_model,
            caption_model=caption_model,
            sd_caption_enabled=sd_caption_enabled,
            sd_caption_single_call_enabled=sd_caption_single_call_enabled,
            sd_caption_model=sd_caption_model,
            sd_caption_system_prompt=sd_caption_system_prompt,
            sd_caption_role_prompt=sd_caption_role_prompt,
            model=legacy_model,  # Keep for reference, not used
            system_prompt=cp.get(
                "openAI",
                "system_prompt",
                fallback="You are a senior social media copywriter. Write authentic, concise, platform-aware captions.",
            ),
            role_prompt=cp.get("openAI", "role_prompt", fallback="Write a caption for:"),
        )
        platforms = PlatformsConfig(
            telegram_enabled=cp.getboolean("Content", "telegram", fallback=False),
            instagram_enabled=cp.getboolean("Content", "instagram", fallback=False),
            email_enabled=cp.getboolean("Content", "fetlife", fallback=False),
        )
        telegram = None
        if platforms.telegram_enabled:
            telegram = TelegramConfig(
                bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
                channel_id=os.environ["TELEGRAM_CHANNEL_ID"],
            )
        instagram = None
        if platforms.instagram_enabled and cp.has_section("Instagram"):
            instagram = InstagramConfig(
                username=cp.get("Instagram", "name"),
                password=os.environ.get("INSTA_PASSWORD", ""),
                session_file="instasession.json",
            )
        email = None
        if platforms.email_enabled and cp.has_section("Email"):
            email = EmailConfig(
                sender=cp.get("Email", "sender"),
                recipient=cp.get("Email", "recipient"),
                password=os.environ["EMAIL_PASSWORD"],
                smtp_server=cp.get("Email", "smtp_server", fallback=os.environ.get("SMTP_SERVER", "smtp.gmail.com")),
                smtp_port=cp.getint("Email", "smtp_port", fallback=int(os.environ.get("SMTP_PORT", "587"))),
                confirmation_to_sender=cp.getboolean("Email", "confirmation_to_sender", fallback=True),
                confirmation_tags_count=cp.getint("Email", "confirmation_tags_count", fallback=5),
                confirmation_tags_nature=cp.get("Email", "confirmation_tags_nature", fallback="short, lowercase, human-friendly topical nouns; no hashtags; no emojis"),
                caption_target=cp.get("Email", "caption_target", fallback="subject"),
                subject_mode=cp.get("Email", "subject_mode", fallback="normal"),
            )
        content = ContentConfig(
            hashtag_string=cp.get("Content", "hashtag_string", fallback=""),
            archive=cp.getboolean("Content", "archive", fallback=True),
            debug=cp.getboolean("Content", "debug", fallback=False),
        )
        # CaptionFile config (Phase 2 extended metadata flag and artist alias)
        captionfile = CaptionFileConfig(
            extended_metadata_enabled=cp.getboolean("CaptionFile", "extended_metadata_enabled", fallback=False),
            artist_alias=cp.get("CaptionFile", "artist_alias", fallback=None)
        )
        features_cfg = FeaturesConfig(
            analyze_caption_enabled=parse_bool_env(
                os.environ.get("FEATURE_ANALYZE_CAPTION"), True, var_name="FEATURE_ANALYZE_CAPTION"
            ),
            publish_enabled=parse_bool_env(
                os.environ.get("FEATURE_PUBLISH"), True, var_name="FEATURE_PUBLISH"
            ),
        )
    except KeyError as exc:
        raise ConfigurationError(f"Missing required environment variable: {exc}") from exc
    except configparser.Error as exc:
        raise ConfigurationError(f"Invalid configuration file: {exc}") from exc

    # Web config is primarily driven by environment variables for MVP.
    # We still construct a typed WebConfig instance here so that future
    # code can depend on it without having to read os.environ directly.
    web_cfg = WebConfig()

    return ApplicationConfig(
        dropbox=dropbox,
        openai=openai_cfg,
        platforms=platforms,
        features=features_cfg,
        telegram=telegram,
        instagram=instagram,
        email=email,
        content=content,
        captionfile=captionfile,
        web=web_cfg,
    )


