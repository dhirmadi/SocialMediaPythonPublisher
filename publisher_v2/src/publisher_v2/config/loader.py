from __future__ import annotations

import configparser
import os
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    EmailConfig,
    InstagramConfig,
    OpenAIConfig,
    PlatformsConfig,
    TelegramConfig,
)
from publisher_v2.core.exceptions import ConfigurationError


def load_application_config(config_file_path: str, env_path: str | None = None) -> ApplicationConfig:
    """
    Load and validate application configuration from INI and .env.
    """
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()

    cp = configparser.ConfigParser()
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
        openai_cfg = OpenAIConfig(
            api_key=os.environ["OPENAI_API_KEY"],
            model=cp.get("openAI", "model", fallback="gpt-4o-mini"),
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
            )
        content = ContentConfig(
            hashtag_string=cp.get("Content", "hashtag_string", fallback=""),
            archive=cp.getboolean("Content", "archive", fallback=True),
            debug=cp.getboolean("Content", "debug", fallback=False),
        )
    except KeyError as exc:
        raise ConfigurationError(f"Missing required environment variable: {exc}") from exc
    except configparser.Error as exc:
        raise ConfigurationError(f"Invalid configuration file: {exc}") from exc

    return ApplicationConfig(
        dropbox=dropbox,
        openai=openai_cfg,
        platforms=platforms,
        telegram=telegram,
        instagram=instagram,
        email=email,
        content=content,
    )


