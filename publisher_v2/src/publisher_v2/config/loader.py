from __future__ import annotations

import configparser
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Optional

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

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
    Auth0Config,
)
from publisher_v2.core.exceptions import ConfigurationError

# Keys to redact when logging configuration (case-insensitive matching)
REDACT_KEYS: set[str] = {
    "password",
    "secret",
    "token",
    "refresh_token",
    "bot_token",
    "api_key",
}


def _parse_json_env(var_name: str) -> Optional[dict | list]:
    """
    Parse JSON from an environment variable.

    Returns:
        Parsed dict/list if the env var is set and contains valid JSON.
        None if the env var is unset or empty.

    Raises:
        ConfigurationError: If the env var contains invalid JSON.
    """
    value = os.environ.get(var_name)
    if not value or not value.strip():
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Invalid JSON in {var_name}: {exc.msg} at position {exc.pos}"
        ) from exc


def _safe_log_config(cfg: dict, redact_keys: set[str] | None = None) -> dict:
    """
    Return a copy of config dict with sensitive values redacted for logging.

    Args:
        cfg: Configuration dictionary to redact.
        redact_keys: Optional set of keys to redact. Defaults to REDACT_KEYS.

    Returns:
        New dict with sensitive values replaced with "***REDACTED***".
    """
    keys_to_redact = redact_keys or REDACT_KEYS
    # Case-insensitive matching
    lower_redact = {k.lower() for k in keys_to_redact}
    return {
        k: "***REDACTED***" if k.lower() in lower_redact else v
        for k, v in cfg.items()
    }


# =============================================================================
# Story 03: Email Server Environment Variable
# =============================================================================


def _load_email_server_from_env() -> dict | None:
    """
    Parse EMAIL_SERVER JSON env var for SMTP configuration.

    Returns:
        Dict with smtp_server, smtp_port, sender if EMAIL_SERVER is set.
        None if EMAIL_SERVER is not set.

    Raises:
        ConfigurationError: If EMAIL_SERVER is invalid or missing required fields.
    """
    parsed = _parse_json_env("EMAIL_SERVER")
    if parsed is None:
        return None

    if "sender" not in parsed:
        raise ConfigurationError("EMAIL_SERVER missing required field 'sender'")

    smtp_server = parsed.get("smtp_server", "smtp.gmail.com")
    smtp_port = parsed.get("smtp_port", 587)

    if not isinstance(smtp_port, int):
        raise ConfigurationError(
            f"EMAIL_SERVER.smtp_port must be an integer, got {type(smtp_port).__name__}"
        )

    return {
        "smtp_server": smtp_server,
        "smtp_port": smtp_port,
        "sender": parsed["sender"],
    }


# =============================================================================
# Story 04: Storage Paths Environment Variable
# =============================================================================


def _resolve_path(base: str, path: str) -> str:
    """Resolve a path relative to base, or return absolute path as-is."""
    if path.startswith("/"):
        return path
    return f"{base.rstrip('/')}/{path}"


def _validate_path_no_traversal(path: str, field: str) -> None:
    """Raise ConfigurationError if path contains '..' component."""
    if ".." in path.split("/"):
        raise ConfigurationError(
            f"STORAGE_PATHS.{field} contains '..' which is not allowed"
        )


def _load_storage_paths_from_env() -> dict | None:
    """
    Parse STORAGE_PATHS JSON env var for Dropbox folder configuration.

    Returns:
        Dict with root, archive, keep, remove paths (all resolved to absolute).
        None if STORAGE_PATHS is not set.

    Raises:
        ConfigurationError: If STORAGE_PATHS is invalid or contains path traversal.
    """
    parsed = _parse_json_env("STORAGE_PATHS")
    if parsed is None:
        return None

    root = parsed.get("root")
    if not root:
        raise ConfigurationError("STORAGE_PATHS missing required field 'root'")
    if not root.startswith("/"):
        raise ConfigurationError(
            "STORAGE_PATHS.root must be an absolute path (start with '/')"
        )
    _validate_path_no_traversal(root, "root")

    # Resolve optional paths with defaults
    archive = _resolve_path(root, parsed.get("archive", "archive"))
    keep = _resolve_path(root, parsed.get("keep", "keep"))
    remove = _resolve_path(root, parsed.get("remove", "reject"))

    # Validate no path traversal in resolved paths
    for name, path in [("archive", archive), ("keep", keep), ("remove", remove)]:
        _validate_path_no_traversal(path, name)

    return {
        "root": root,
        "archive": archive,
        "keep": keep,
        "remove": remove,
    }


# =============================================================================
# Story 05: OpenAI and Metadata Settings
# =============================================================================


def _load_openai_settings_from_env() -> dict | None:
    """Parse OPENAI_SETTINGS JSON env var for AI model configuration."""
    parsed = _parse_json_env("OPENAI_SETTINGS")
    if parsed is None:
        return None
    return {
        "vision_model": parsed.get("vision_model", "gpt-4o"),
        "caption_model": parsed.get("caption_model", "gpt-4o-mini"),
        "system_prompt": parsed.get("system_prompt"),
        "role_prompt": parsed.get("role_prompt"),
        "sd_caption_enabled": parsed.get("sd_caption_enabled", True),
        "sd_caption_single_call_enabled": parsed.get("sd_caption_single_call_enabled", True),
        "sd_caption_model": parsed.get("sd_caption_model"),
        "sd_caption_system_prompt": parsed.get("sd_caption_system_prompt"),
        "sd_caption_role_prompt": parsed.get("sd_caption_role_prompt"),
    }


def _load_captionfile_settings_from_env() -> dict | None:
    """Parse CAPTIONFILE_SETTINGS JSON env var for caption file metadata."""
    parsed = _parse_json_env("CAPTIONFILE_SETTINGS")
    if parsed is None:
        return None
    return {
        "extended_metadata_enabled": parsed.get("extended_metadata_enabled", False),
        "artist_alias": parsed.get("artist_alias"),
    }


def _load_confirmation_settings_from_env() -> dict | None:
    """Parse CONFIRMATION_SETTINGS JSON env var for confirmation email behavior."""
    parsed = _parse_json_env("CONFIRMATION_SETTINGS")
    if parsed is None:
        return None
    return {
        "confirmation_to_sender": parsed.get("confirmation_to_sender", True),
        "confirmation_tags_count": parsed.get("confirmation_tags_count", 5),
        "confirmation_tags_nature": parsed.get("confirmation_tags_nature"),
    }


def _load_content_settings_from_env() -> dict | None:
    """Parse CONTENT_SETTINGS JSON env var for content configuration."""
    parsed = _parse_json_env("CONTENT_SETTINGS")
    if parsed is None:
        return None
    return {
        "hashtag_string": parsed.get("hashtag_string", ""),
        "archive": parsed.get("archive", True),
        "debug": parsed.get("debug", False),
    }


# =============================================================================
# Story 02: Publishers Environment Variable
# =============================================================================


def _load_publishers_from_env(
    entries: list,
    email_server: dict | None,
    cp: configparser.ConfigParser,
) -> tuple[TelegramConfig | None, InstagramConfig | None, EmailConfig | None, PlatformsConfig]:
    """
    Parse PUBLISHERS JSON array and create publisher configurations.

    Args:
        entries: Parsed PUBLISHERS JSON array.
        email_server: Parsed EMAIL_SERVER config (or None).
        cp: ConfigParser for INI fallback values.

    Returns:
        Tuple of (TelegramConfig, InstagramConfig, EmailConfig, PlatformsConfig).

    Raises:
        ConfigurationError: If duplicate types or missing required secrets.
    """
    # Validate no duplicate types
    seen_types: set[str] = set()
    for entry in entries:
        entry_type = entry.get("type")
        if entry_type in seen_types:
            raise ConfigurationError(
                f"Duplicate publisher type '{entry_type}' in PUBLISHERS"
            )
        if entry_type:
            seen_types.add(entry_type)

    telegram: TelegramConfig | None = None
    instagram: InstagramConfig | None = None
    email: EmailConfig | None = None
    telegram_enabled = False
    instagram_enabled = False
    email_enabled = False

    # Get confirmation settings from env or INI
    confirmation_settings = _load_confirmation_settings_from_env()

    for entry in entries:
        entry_type = entry.get("type")

        if entry_type == "telegram":
            bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
            if not bot_token:
                raise ConfigurationError(
                    "TELEGRAM_BOT_TOKEN required when telegram publisher is configured in PUBLISHERS"
                )
            channel_id = entry.get("channel_id")
            if not channel_id:
                raise ConfigurationError(
                    "PUBLISHERS telegram entry missing required field 'channel_id'"
                )
            telegram = TelegramConfig(
                bot_token=bot_token,
                channel_id=channel_id,
            )
            telegram_enabled = True

        elif entry_type == "fetlife":
            password = os.environ.get("EMAIL_PASSWORD")
            if not password:
                raise ConfigurationError(
                    "EMAIL_PASSWORD required when fetlife publisher is configured in PUBLISHERS"
                )
            recipient = entry.get("recipient")
            if not recipient:
                raise ConfigurationError(
                    "PUBLISHERS fetlife entry missing required field 'recipient'"
                )

            # Get SMTP settings from EMAIL_SERVER or fallback
            if email_server:
                smtp_server = email_server["smtp_server"]
                smtp_port = email_server["smtp_port"]
                sender = email_server["sender"]
            else:
                # Fallback to INI/env
                smtp_server = cp.get("Email", "smtp_server", fallback=os.environ.get("SMTP_SERVER", "smtp.gmail.com"))
                smtp_port = cp.getint("Email", "smtp_port", fallback=int(os.environ.get("SMTP_PORT", "587")))
                sender = cp.get("Email", "sender", fallback="")

            # Get confirmation settings
            if confirmation_settings:
                conf_to_sender = confirmation_settings["confirmation_to_sender"]
                conf_tags_count = confirmation_settings["confirmation_tags_count"]
                conf_tags_nature = confirmation_settings.get("confirmation_tags_nature") or "short, lowercase, human-friendly topical nouns; no hashtags; no emojis"
            else:
                conf_to_sender = cp.getboolean("Email", "confirmation_to_sender", fallback=True)
                conf_tags_count = cp.getint("Email", "confirmation_tags_count", fallback=5)
                conf_tags_nature = cp.get("Email", "confirmation_tags_nature", fallback="short, lowercase, human-friendly topical nouns; no hashtags; no emojis")

            email = EmailConfig(
                sender=sender,
                recipient=recipient,
                password=password,
                smtp_server=smtp_server,
                smtp_port=smtp_port,
                confirmation_to_sender=conf_to_sender,
                confirmation_tags_count=conf_tags_count,
                confirmation_tags_nature=conf_tags_nature,
                caption_target=entry.get("caption_target", "subject"),
                subject_mode=entry.get("subject_mode", "normal"),
            )
            email_enabled = True

        elif entry_type == "instagram":
            password = os.environ.get("INSTA_PASSWORD")
            if not password:
                raise ConfigurationError(
                    "INSTA_PASSWORD required when instagram publisher is configured in PUBLISHERS"
                )
            username = entry.get("username")
            if not username:
                raise ConfigurationError(
                    "PUBLISHERS instagram entry missing required field 'username'"
                )
            instagram = InstagramConfig(
                username=username,
                password=password,
                session_file="instasession.json",
            )
            instagram_enabled = True

        else:
            logger.warning(f"Unknown publisher type '{entry_type}' in PUBLISHERS - skipping")

    platforms = PlatformsConfig(
        telegram_enabled=telegram_enabled,
        instagram_enabled=instagram_enabled,
        email_enabled=email_enabled,
    )

    return telegram, instagram, email, platforms


# =============================================================================
# Story 06: Deprecation Warnings
# =============================================================================


def log_config_source(
    source: str,
    ini_sections_used: list[str] | None = None,
    publishers_count: int = 0,
    storage_source: str = "unknown",
) -> None:
    """
    Log the configuration source at startup.

    Args:
        source: Either "env_vars" (all env-based) or "ini_fallback" (some INI used).
        ini_sections_used: List of INI sections that were used as fallback.
        publishers_count: Number of publishers configured.
        storage_source: "STORAGE_PATHS" or "INI".
    """
    if source == "env_vars":
        logger.info(
            "Config source: env_vars | publishers=%d | storage=%s",
            publishers_count,
            storage_source,
        )
    else:
        sections_str = ", ".join(ini_sections_used or [])
        logger.warning(
            "Config source: ini_fallback (migrate to env vars) | "
            "INI sections used: [%s] | publishers=%d | storage=%s",
            sections_str,
            publishers_count,
            storage_source,
        )


def log_deprecation_warning(ini_sections: list[str]) -> None:
    """
    Log deprecation warning when INI fallback is used.

    Args:
        ini_sections: List of INI sections that triggered fallback.
    """
    if ini_sections:
        logger.warning(
            "DEPRECATION: INI-based config is deprecated. "
            "Migrate to JSON env vars (PUBLISHERS, EMAIL_SERVER, STORAGE_PATHS, etc.). "
            "INI sections used: %s",
            ini_sections,
        )


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


def load_application_config(
    config_file_path: str | None = None, env_path: str | None = None
) -> ApplicationConfig:
    """
    Load and validate application configuration.

    Precedence order (first found wins):
    1. New JSON environment variables (PUBLISHERS, STORAGE_PATHS, etc.)
    2. Old individual environment variables
    3. INI file sections (backward compatibility)

    When all required JSON env vars are set (STORAGE_PATHS, PUBLISHERS, OPENAI_SETTINGS),
    the INI file is optional. Otherwise, config_file_path must point to a valid INI file.

    Emits deprecation warnings when INI fallback is used.
    """
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()

    # Track which INI sections are used for deprecation warnings
    ini_sections_used: list[str] = []

    # Check if we have all required env vars for env-first mode
    has_storage_paths = os.environ.get("STORAGE_PATHS")
    has_publishers = os.environ.get("PUBLISHERS") is not None  # Empty [] is valid
    has_openai_settings = os.environ.get("OPENAI_SETTINGS")

    env_first_mode = has_storage_paths and has_publishers and has_openai_settings

    # Configure parser to handle inline comments (e.g., "value ; comment")
    cp = configparser.ConfigParser(inline_comment_prefixes=(';', '#'))

    # Handle INI file loading
    if config_file_path:
        # User explicitly provided a path - it must exist
        if not os.path.exists(config_file_path):
            raise ConfigurationError(f"Config file not found: {config_file_path}")
        cp.read(config_file_path)
    elif not env_first_mode:
        # No path provided and not in env-first mode - error
        raise ConfigurationError(
            "Either config_file_path must be provided or all required env vars must be set: "
            "STORAGE_PATHS, PUBLISHERS, OPENAI_SETTINGS"
        )
    # else: env-first mode with no INI file - OK

    try:
        # =====================================================================
        # STORAGE / DROPBOX CONFIG
        # =====================================================================
        storage_paths = _load_storage_paths_from_env()
        if storage_paths:
            # Use STORAGE_PATHS env var
            image_folder = storage_paths["root"]
            archive_folder = storage_paths["archive"]
            folder_keep = storage_paths["keep"]
            folder_remove = storage_paths["remove"]
            storage_source = "STORAGE_PATHS"
        else:
            # Fallback to INI [Dropbox] section
            ini_sections_used.append("Dropbox")
            storage_source = "INI"
            image_folder = cp.get("Dropbox", "image_folder")
            archive_folder = cp.get("Dropbox", "archive", fallback="archive")

            # Optional keep/remove folders with legacy alias support
            folder_keep = cp.get("Dropbox", "folder_keep", fallback="keep")
            folder_remove = cp.get("Dropbox", "folder_remove", fallback=None)
            if folder_remove is None:
                if cp.has_option("Dropbox", "folder_reject"):
                    folder_remove = cp.get("Dropbox", "folder_reject")
                else:
                    folder_remove = "reject"

            # Environment overrides (lowercase, as requested for V2)
            env_keep = os.environ.get("folder_keep")
            env_remove = os.environ.get("folder_remove")
            if env_keep is not None and env_keep.strip():
                folder_keep = env_keep.strip()
            if env_remove is not None and env_remove.strip():
                folder_remove = env_remove.strip()

            # Validate subfolder names (INI mode uses relative paths)
            def _validate_subfolder(name: str | None, field_name: str) -> str | None:
                if name is None:
                    return None
                trimmed = name.strip()
                if not trimmed:
                    return None
                if any(sep in trimmed for sep in ("/", "\\", "..")):
                    raise ConfigurationError(
                        f"Invalid value '{name}' for {field_name}; "
                        "must be a simple subfolder name without path separators or '..'."
                    )
                return trimmed

            folder_keep = _validate_subfolder(folder_keep, "[Dropbox].folder_keep")
            folder_remove = _validate_subfolder(folder_remove, "[Dropbox].folder_remove")

        dropbox = DropboxConfig(
            app_key=os.environ["DROPBOX_APP_KEY"],
            app_secret=os.environ["DROPBOX_APP_SECRET"],
            refresh_token=os.environ["DROPBOX_REFRESH_TOKEN"],
            image_folder=image_folder,
            archive_folder=archive_folder,
            folder_keep=folder_keep,
            folder_remove=folder_remove,
        )

        # =====================================================================
        # OPENAI CONFIG
        # =====================================================================
        openai_settings = _load_openai_settings_from_env()
        if openai_settings:
            # Use OPENAI_SETTINGS env var
            vision_model = openai_settings["vision_model"]
            caption_model = openai_settings["caption_model"]
            system_prompt = openai_settings.get("system_prompt") or "You are a senior social media copywriter. Write authentic, concise, platform-aware captions."
            role_prompt = openai_settings.get("role_prompt") or "Write a caption for:"
            sd_caption_enabled = openai_settings["sd_caption_enabled"]
            sd_caption_single_call_enabled = openai_settings["sd_caption_single_call_enabled"]
            sd_caption_model = openai_settings.get("sd_caption_model")
            sd_caption_system_prompt = openai_settings.get("sd_caption_system_prompt")
            sd_caption_role_prompt = openai_settings.get("sd_caption_role_prompt")
            legacy_model = None
        else:
            # Fallback to INI [openAI] section
            ini_sections_used.append("openAI")
            vision_model = cp.get("openAI", "vision_model", fallback=None)
            caption_model = cp.get("openAI", "caption_model", fallback=None)
            legacy_model = cp.get("openAI", "model", fallback=None)
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

            system_prompt = cp.get(
                "openAI",
                "system_prompt",
                fallback="You are a senior social media copywriter. Write authentic, concise, platform-aware captions.",
            )
            role_prompt = cp.get("openAI", "role_prompt", fallback="Write a caption for:")

        openai_cfg = OpenAIConfig(
            api_key=os.environ["OPENAI_API_KEY"],
            vision_model=vision_model,
            caption_model=caption_model,
            sd_caption_enabled=sd_caption_enabled,
            sd_caption_single_call_enabled=sd_caption_single_call_enabled,
            sd_caption_model=sd_caption_model,
            sd_caption_system_prompt=sd_caption_system_prompt,
            sd_caption_role_prompt=sd_caption_role_prompt,
            model=legacy_model,
            system_prompt=system_prompt,
            role_prompt=role_prompt,
        )

        # =====================================================================
        # PUBLISHERS CONFIG
        # =====================================================================
        publishers_json = _parse_json_env("PUBLISHERS")
        email_server = _load_email_server_from_env()

        if publishers_json is not None:
            # Use PUBLISHERS env var - derive enabled state from array
            telegram, instagram, email, platforms = _load_publishers_from_env(
                publishers_json, email_server, cp
            )
            publishers_source = "PUBLISHERS"
            publishers_count = len(publishers_json)
        else:
            # Fallback to INI [Content] toggles
            ini_sections_used.append("Content")
            publishers_source = "INI"
            publishers_count = 0

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
                publishers_count += 1

            instagram = None
            if platforms.instagram_enabled and cp.has_section("Instagram"):
                ini_sections_used.append("Instagram")
                instagram = InstagramConfig(
                    username=cp.get("Instagram", "name"),
                    password=os.environ.get("INSTA_PASSWORD", ""),
                    session_file="instasession.json",
                )
                publishers_count += 1

            email = None
            if platforms.email_enabled and cp.has_section("Email"):
                ini_sections_used.append("Email")
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
                publishers_count += 1

        # =====================================================================
        # CONTENT CONFIG
        # =====================================================================
        content_settings = _load_content_settings_from_env()
        if content_settings:
            content = ContentConfig(
                hashtag_string=content_settings["hashtag_string"],
                archive=content_settings["archive"],
                debug=content_settings["debug"],
            )
        else:
            # Content section already tracked if PUBLISHERS fallback was used
            if "Content" not in ini_sections_used:
                ini_sections_used.append("Content")
            content = ContentConfig(
                hashtag_string=cp.get("Content", "hashtag_string", fallback=""),
                archive=cp.getboolean("Content", "archive", fallback=True),
                debug=cp.getboolean("Content", "debug", fallback=False),
            )

        # =====================================================================
        # CAPTIONFILE CONFIG
        # =====================================================================
        captionfile_settings = _load_captionfile_settings_from_env()
        if captionfile_settings:
            captionfile = CaptionFileConfig(
                extended_metadata_enabled=captionfile_settings["extended_metadata_enabled"],
                artist_alias=captionfile_settings.get("artist_alias"),
            )
        else:
            if cp.has_section("CaptionFile"):
                ini_sections_used.append("CaptionFile")
            captionfile = CaptionFileConfig(
                extended_metadata_enabled=cp.getboolean("CaptionFile", "extended_metadata_enabled", fallback=False),
                artist_alias=cp.get("CaptionFile", "artist_alias", fallback=None),
            )

        # =====================================================================
        # FEATURES CONFIG (always from env vars)
        # =====================================================================
        features_cfg = FeaturesConfig(
            analyze_caption_enabled=parse_bool_env(
                os.environ.get("FEATURE_ANALYZE_CAPTION"), True, var_name="FEATURE_ANALYZE_CAPTION"
            ),
            publish_enabled=parse_bool_env(
                os.environ.get("FEATURE_PUBLISH"), True, var_name="FEATURE_PUBLISH"
            ),
            keep_enabled=parse_bool_env(
                os.environ.get("FEATURE_KEEP_CURATE"), True, var_name="FEATURE_KEEP_CURATE"
            ),
            remove_enabled=parse_bool_env(
                os.environ.get("FEATURE_REMOVE_CURATE"), True, var_name="FEATURE_REMOVE_CURATE"
            ),
            auto_view_enabled=parse_bool_env(
                os.environ.get("AUTO_VIEW"), False, var_name="AUTO_VIEW"
            ),
        )

    except KeyError as exc:
        raise ConfigurationError(f"Missing required environment variable: {exc}") from exc
    except configparser.Error as exc:
        raise ConfigurationError(f"Invalid configuration file: {exc}") from exc

    # =========================================================================
    # DEPRECATION WARNINGS
    # =========================================================================
    # Remove duplicates and sort for consistent logging
    ini_sections_used = sorted(set(ini_sections_used))

    if ini_sections_used:
        log_deprecation_warning(ini_sections_used)
        log_config_source(
            "ini_fallback",
            ini_sections_used=ini_sections_used,
            publishers_count=publishers_count,
            storage_source=storage_source,
        )
    else:
        log_config_source(
            "env_vars",
            publishers_count=publishers_count,
            storage_source=storage_source,
        )

    # =========================================================================
    # WEB & AUTH0 CONFIG
    # =========================================================================
    web_cfg = WebConfig()

    auth0_cfg = None
    if os.environ.get("AUTH0_DOMAIN") and os.environ.get("AUTH0_CLIENT_ID"):
        try:
            auth0_cfg = Auth0Config(
                domain=os.environ["AUTH0_DOMAIN"],
                client_id=os.environ["AUTH0_CLIENT_ID"],
                client_secret=os.environ["AUTH0_CLIENT_SECRET"],
                audience=os.environ.get("AUTH0_AUDIENCE"),
                callback_url=os.environ.get("AUTH0_CALLBACK_URL"),
                admin_emails=os.environ.get("ADMIN_LOGIN_EMAILS") or os.environ["AUTH0_ADMIN_EMAIL_ALLOWLIST"],
            )
        except KeyError as exc:
            raise ConfigurationError(f"Missing required Auth0 environment variable: {exc}") from exc

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
        auth0=auth0_cfg,
    )


