from __future__ import annotations

import json
import logging
import os
from typing import Any

from dotenv import load_dotenv

from publisher_v2.config.schema import (
    ApplicationConfig,
    Auth0Config,
    CaptionFileConfig,
    ContentConfig,
    DropboxConfig,
    EmailConfig,
    FeaturesConfig,
    InstagramConfig,
    ManagedStorageConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
    TelegramConfig,
    WebConfig,
)
from publisher_v2.core.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

# Keys to redact when logging configuration (case-insensitive matching)
REDACT_KEYS: set[str] = {
    "password",
    "secret",
    "token",
    "refresh_token",
    "bot_token",
    "api_key",
    "voice_profile",
}


def _parse_json_env(var_name: str) -> dict | list | None:
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
        result: dict[Any, Any] | list[Any] = json.loads(value)
        return result
    except json.JSONDecodeError as exc:
        raise ConfigurationError(f"Invalid JSON in {var_name}: {exc.msg} at position {exc.pos}") from exc


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
    return {k: "***REDACTED***" if k.lower() in lower_redact else v for k, v in cfg.items()}


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
    if not isinstance(parsed, dict):
        raise ConfigurationError("EMAIL_SERVER must be a JSON object")

    if "sender" not in parsed:
        raise ConfigurationError("EMAIL_SERVER missing required field 'sender'")

    smtp_server = parsed.get("smtp_server", "smtp.gmail.com")
    smtp_port = parsed.get("smtp_port", 587)

    if not isinstance(smtp_port, int):
        raise ConfigurationError(f"EMAIL_SERVER.smtp_port must be an integer, got {type(smtp_port).__name__}")

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
        raise ConfigurationError(f"STORAGE_PATHS.{field} contains '..' which is not allowed")


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
    if not isinstance(parsed, dict):
        raise ConfigurationError("STORAGE_PATHS must be a JSON object")

    root = parsed.get("root")
    if not root:
        raise ConfigurationError("STORAGE_PATHS missing required field 'root'")
    if not root.startswith("/"):
        raise ConfigurationError("STORAGE_PATHS.root must be an absolute path (start with '/')")
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
    if not isinstance(parsed, dict):
        raise ConfigurationError("OPENAI_SETTINGS must be a JSON object")
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
        # PUB-041: vision cost optimization
        "vision_max_dimension": parsed.get("vision_max_dimension", 1024),
        "vision_detail": parsed.get("vision_detail", "low"),
        "vision_fallback_enabled": parsed.get("vision_fallback_enabled", True),
        "vision_fallback_max_dimension": parsed.get("vision_fallback_max_dimension", 2048),
        "vision_fallback_detail": parsed.get("vision_fallback_detail", "high"),
    }


def _load_captionfile_settings_from_env() -> dict | None:
    """Parse CAPTIONFILE_SETTINGS JSON env var for caption file metadata."""
    parsed = _parse_json_env("CAPTIONFILE_SETTINGS")
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        raise ConfigurationError("CAPTIONFILE_SETTINGS must be a JSON object")
    return {
        "extended_metadata_enabled": parsed.get("extended_metadata_enabled", False),
        "artist_alias": parsed.get("artist_alias"),
    }


def _load_confirmation_settings_from_env() -> dict | None:
    """Parse CONFIRMATION_SETTINGS JSON env var for confirmation email behavior."""
    parsed = _parse_json_env("CONFIRMATION_SETTINGS")
    if parsed is None:
        return None
    if not isinstance(parsed, dict):
        raise ConfigurationError("CONFIRMATION_SETTINGS must be a JSON object")
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
    if not isinstance(parsed, dict):
        raise ConfigurationError("CONTENT_SETTINGS must be a JSON object")
    result: dict = {
        "hashtag_string": parsed.get("hashtag_string", ""),
        "archive": parsed.get("archive", True),
        "debug": parsed.get("debug", False),
    }
    if "voice_profile" in parsed:
        result["voice_profile"] = parsed["voice_profile"]
    return result


# =============================================================================
# Story 02: Publishers Environment Variable
# =============================================================================


def _load_publishers_from_env(
    entries: list,
    email_server: dict | None,
) -> tuple[TelegramConfig | None, InstagramConfig | None, EmailConfig | None, PlatformsConfig]:
    """
    Parse PUBLISHERS JSON array and create publisher configurations.

    Args:
        entries: Parsed PUBLISHERS JSON array.
        email_server: Parsed EMAIL_SERVER config (or None).

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
            raise ConfigurationError(f"Duplicate publisher type '{entry_type}' in PUBLISHERS")
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
                raise ConfigurationError("PUBLISHERS telegram entry missing required field 'channel_id'")
            telegram = TelegramConfig(
                bot_token=bot_token,
                channel_id=channel_id,
            )
            telegram_enabled = True

        elif entry_type == "fetlife":
            password = os.environ.get("EMAIL_PASSWORD")
            if not password:
                raise ConfigurationError("EMAIL_PASSWORD required when fetlife publisher is configured in PUBLISHERS")
            recipient = entry.get("recipient")
            if not recipient:
                raise ConfigurationError("PUBLISHERS fetlife entry missing required field 'recipient'")

            # Get SMTP settings from EMAIL_SERVER or legacy flat env vars
            if email_server:
                smtp_server = email_server["smtp_server"]
                smtp_port = email_server["smtp_port"]
                sender = email_server["sender"]
            else:
                smtp_server = os.environ.get("SMTP_SERVER", "smtp.gmail.com")
                smtp_port = int(os.environ.get("SMTP_PORT", "587"))
                sender = ""

            # Get confirmation settings
            if confirmation_settings:
                conf_to_sender = confirmation_settings["confirmation_to_sender"]
                conf_tags_count = confirmation_settings["confirmation_tags_count"]
                conf_tags_nature = (
                    confirmation_settings.get("confirmation_tags_nature")
                    or "short, lowercase, human-friendly topical nouns; no hashtags; no emojis"
                )
            else:
                conf_to_sender = True
                conf_tags_count = 5
                conf_tags_nature = "short, lowercase, human-friendly topical nouns; no hashtags; no emojis"

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
                raise ConfigurationError("INSTA_PASSWORD required when instagram publisher is configured in PUBLISHERS")
            username = entry.get("username")
            if not username:
                raise ConfigurationError("PUBLISHERS instagram entry missing required field 'username'")
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
    source: str = "env_vars",
    ini_sections_used: list[str] | None = None,
    publishers_count: int = 0,
    storage_source: str = "STORAGE_PATHS",
) -> None:
    """Log the configuration source at startup.

    #97 stage 4: INI support removed — env_vars is the only source. The first
    two parameters are kept for call-site compatibility and ignored.
    """
    logger.info(
        "Config source: env_vars | publishers=%d | storage=%s",
        publishers_count,
        storage_source,
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


def load_application_config(config_file_path: str | None = None, env_path: str | None = None) -> ApplicationConfig:
    """
    Load and validate application configuration from environment variables.

    #97 stage 4: INI support is removed. Configuration comes from JSON env
    vars (STORAGE_PATHS, PUBLISHERS, OPENAI_SETTINGS, and the optional
    EMAIL_SERVER / CONTENT_SETTINGS / CAPTIONFILE_SETTINGS /
    CONFIRMATION_SETTINGS blobs). ``config_file_path`` is accepted for CLI
    backward compatibility but its contents are ignored (a warning is logged).
    """
    if env_path:
        load_dotenv(env_path)
    else:
        load_dotenv()

    if config_file_path:
        logger.warning(
            "INI configuration was removed (#97 stage 4); ignoring --config file %s. "
            "Use STORAGE_PATHS, PUBLISHERS, OPENAI_SETTINGS env vars.",
            config_file_path,
        )

    missing = [
        name
        for name, present in (
            ("STORAGE_PATHS", bool(os.environ.get("STORAGE_PATHS"))),
            ("PUBLISHERS", os.environ.get("PUBLISHERS") is not None),  # empty [] is valid
            ("OPENAI_SETTINGS", bool(os.environ.get("OPENAI_SETTINGS"))),
        )
        if not present
    ]
    if missing:
        raise ConfigurationError(
            "INI configuration was removed (#97 stage 4); required env vars not set: " + ", ".join(missing)
        )

    try:
        # =====================================================================
        # STORAGE / DROPBOX CONFIG
        # =====================================================================
        storage_paths = _load_storage_paths_from_env()
        if storage_paths is None:
            raise ConfigurationError("STORAGE_PATHS env var is required (INI [Dropbox] support removed, #97 stage 4)")
        image_folder = storage_paths["root"]
        archive_folder = storage_paths["archive"]
        folder_keep = storage_paths["keep"]
        folder_remove = storage_paths["remove"]
        storage_source = "STORAGE_PATHS"

        storage_provider = (os.environ.get("STORAGE_PROVIDER") or "dropbox").strip().lower()
        dropbox: DropboxConfig | None = None
        managed: ManagedStorageConfig | None = None

        if storage_provider == "managed":
            managed = ManagedStorageConfig(
                access_key_id=os.environ["R2_ACCESS_KEY_ID"],
                secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],
                endpoint_url=os.environ["R2_ENDPOINT_URL"],
                bucket=os.environ["R2_BUCKET_NAME"],
                region=os.environ.get("R2_REGION", "auto"),
            )
        else:
            dropbox = DropboxConfig(
                app_key=os.environ["DROPBOX_APP_KEY"],
                app_secret=os.environ["DROPBOX_APP_SECRET"],
                refresh_token=os.environ["DROPBOX_REFRESH_TOKEN"],
                image_folder=image_folder,
                archive_folder=archive_folder,
                folder_keep=folder_keep,
                folder_remove=folder_remove,
            )

        storage_path_cfg = StoragePathConfig(
            image_folder=image_folder,
            archive_folder=archive_folder,
            folder_keep=folder_keep,
            folder_remove=folder_remove,
        )

        # =====================================================================
        # OPENAI CONFIG
        # =====================================================================
        openai_settings = _load_openai_settings_from_env()
        # PUB-041 vision fields default to schema values; only overridden when env-mode in use.
        vision_max_dimension: int = 1024
        vision_detail: str = "low"
        vision_fallback_enabled: bool = True
        vision_fallback_max_dimension: int = 2048
        vision_fallback_detail: str = "high"
        if openai_settings is None:
            raise ConfigurationError("OPENAI_SETTINGS env var is required (INI [openAI] support removed, #97 stage 4)")
        vision_model = openai_settings["vision_model"]
        caption_model = openai_settings["caption_model"]
        system_prompt = (
            openai_settings.get("system_prompt")
            or "You are a senior social media copywriter. Write authentic, concise, platform-aware captions."
        )
        role_prompt = openai_settings.get("role_prompt") or "Write a caption for:"
        sd_caption_enabled = openai_settings["sd_caption_enabled"]
        sd_caption_single_call_enabled = openai_settings["sd_caption_single_call_enabled"]
        sd_caption_model = openai_settings.get("sd_caption_model")
        sd_caption_system_prompt = openai_settings.get("sd_caption_system_prompt")
        sd_caption_role_prompt = openai_settings.get("sd_caption_role_prompt")
        vision_max_dimension = int(openai_settings["vision_max_dimension"])
        vision_detail = openai_settings["vision_detail"]
        vision_fallback_enabled = bool(openai_settings["vision_fallback_enabled"])
        vision_fallback_max_dimension = int(openai_settings["vision_fallback_max_dimension"])
        vision_fallback_detail = openai_settings["vision_fallback_detail"]

        openai_cfg = OpenAIConfig(
            api_key=os.environ["OPENAI_API_KEY"],
            vision_model=vision_model,
            caption_model=caption_model,
            sd_caption_enabled=sd_caption_enabled,
            sd_caption_single_call_enabled=sd_caption_single_call_enabled,
            sd_caption_model=sd_caption_model,
            sd_caption_system_prompt=sd_caption_system_prompt,
            sd_caption_role_prompt=sd_caption_role_prompt,
            model=None,  # legacy INI-only field; always None since #97 stage 4
            system_prompt=system_prompt,
            role_prompt=role_prompt,
            vision_max_dimension=vision_max_dimension,
            vision_detail=vision_detail,
            vision_fallback_enabled=vision_fallback_enabled,
            vision_fallback_max_dimension=vision_fallback_max_dimension,
            vision_fallback_detail=vision_fallback_detail,
        )

        # =====================================================================
        # PUBLISHERS CONFIG
        # =====================================================================
        publishers_json = _parse_json_env("PUBLISHERS")
        email_server = _load_email_server_from_env()

        if publishers_json is None:
            raise ConfigurationError("PUBLISHERS env var is required (INI [Content] toggles removed, #97 stage 4)")
        if not isinstance(publishers_json, list):
            raise ConfigurationError("PUBLISHERS must be a JSON array")
        telegram, instagram, email, platforms = _load_publishers_from_env(publishers_json, email_server)
        publishers_count = len(publishers_json)

        # =====================================================================
        # CONTENT CONFIG
        # =====================================================================
        content_settings = _load_content_settings_from_env()
        if content_settings:
            content = ContentConfig(
                hashtag_string=content_settings["hashtag_string"],
                archive=content_settings["archive"],
                debug=content_settings["debug"],
                voice_profile=content_settings.get("voice_profile"),
            )
        else:
            # CONTENT_SETTINGS unset: schema defaults (INI [Content] removed, #97 stage 4)
            content = ContentConfig(hashtag_string="", archive=True, debug=False, voice_profile=None)

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
            # CAPTIONFILE_SETTINGS unset: defaults (INI [CaptionFile] removed, #97 stage 4)
            captionfile = CaptionFileConfig(extended_metadata_enabled=False, artist_alias=None)

        # =====================================================================
        # FEATURES CONFIG (always from env vars)
        # =====================================================================
        features_cfg = FeaturesConfig(
            analyze_caption_enabled=parse_bool_env(
                os.environ.get("FEATURE_ANALYZE_CAPTION"), True, var_name="FEATURE_ANALYZE_CAPTION"
            ),
            publish_enabled=parse_bool_env(os.environ.get("FEATURE_PUBLISH"), True, var_name="FEATURE_PUBLISH"),
            keep_enabled=parse_bool_env(os.environ.get("FEATURE_KEEP_CURATE"), True, var_name="FEATURE_KEEP_CURATE"),
            remove_enabled=parse_bool_env(
                os.environ.get("FEATURE_REMOVE_CURATE"), True, var_name="FEATURE_REMOVE_CURATE"
            ),
            auto_view_enabled=parse_bool_env(os.environ.get("AUTO_VIEW"), False, var_name="AUTO_VIEW"),
            alt_text_enabled=parse_bool_env(os.environ.get("FEATURE_ALT_TEXT"), True, var_name="FEATURE_ALT_TEXT"),
            smart_hashtags_enabled=parse_bool_env(
                os.environ.get("FEATURE_SMART_HASHTAGS"), True, var_name="FEATURE_SMART_HASHTAGS"
            ),
            voice_matching_enabled=parse_bool_env(
                os.environ.get("FEATURE_VOICE_MATCHING"), False, var_name="FEATURE_VOICE_MATCHING"
            ),
            storage_ops_metering_enabled=parse_bool_env(
                os.environ.get("FEATURE_STORAGE_OPS_METERING"),
                False,
                var_name="FEATURE_STORAGE_OPS_METERING",
            ),
        )

    except KeyError as exc:
        raise ConfigurationError(f"Missing required environment variable: {exc}") from exc

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
                admin_emails=os.environ.get("ADMIN_LOGIN_EMAILS")
                or os.environ.get("AUTH0_ADMIN_EMAIL_ALLOWLIST")
                or "",
            )
        except KeyError as exc:
            raise ConfigurationError(f"Missing required Auth0 environment variable: {exc}") from exc

    return ApplicationConfig(
        dropbox=dropbox,
        managed=managed,
        storage_paths=storage_path_cfg,
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
