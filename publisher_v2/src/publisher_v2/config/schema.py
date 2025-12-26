from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from typing import Optional


class DropboxConfig(BaseModel):
    app_key: str = Field(..., description="Dropbox application key")
    app_secret: str = Field(..., description="Dropbox application secret")
    refresh_token: str = Field(..., description="OAuth2 refresh token")
    image_folder: str = Field(..., description="Source image folder path in Dropbox")
    archive_folder: str = Field(default="archive", description="Archive folder name (relative)")
    folder_keep: str = Field(
        default="keep",
        description="Subfolder name under image_folder for Keep curation moves",
    )
    folder_remove: str = Field(
        default="reject",
        description="Subfolder name under image_folder for Remove curation moves (alias for legacy folder_reject)",
    )

    @field_validator("image_folder")
    @classmethod
    def validate_folder_path(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("Dropbox folder path must start with /")
        return v


class OpenAIConfig(BaseModel):
    # In orchestrator mode, api_key may be resolved lazily; loader still requires it.
    api_key: Optional[str] = Field(default=None, description="OpenAI API key")
    
    # Separate models for optimal quality/cost balance
    vision_model: str = Field(
        default="gpt-4o",
        description="OpenAI model for image vision analysis (gpt-4o recommended for best quality)",
    )
    caption_model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model for caption generation (gpt-4o-mini is cost-effective)",
    )
    # Stable-Diffusion style caption sidecar feature flags and options
    sd_caption_enabled: bool = Field(
        default=True,
        description="Enable generation of Stable-Diffusion-ready sidecar caption",
    )
    sd_caption_single_call_enabled: bool = Field(
        default=True,
        description="Prefer single caption-model call returning {caption, sd_caption}",
    )
    sd_caption_model: Optional[str] = Field(
        default=None,
        description="Optional override model for SD caption single-call generation",
    )
    sd_caption_system_prompt: Optional[str] = Field(
        default=None,
        description="Optional system prompt override for SD caption generation",
    )
    sd_caption_role_prompt: Optional[str] = Field(
        default=None,
        description="Optional role/user prompt override for SD caption generation",
    )
    
    # Deprecated: kept for backward compatibility
    model: Optional[str] = Field(
        default=None,
        description="(Deprecated) Single model for both tasks. Use vision_model and caption_model instead.",
    )
    
    system_prompt: str = Field(
        default="You are a senior social media copywriter. Write authentic, concise, platform-aware captions.",
        description="System prompt used for caption generation",
    )
    role_prompt: str = Field(default="Write a caption for:", description="Role/user prompt prefix")

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not v.startswith("sk-"):
            raise ValueError("Invalid OpenAI API key format")
        return v
    
    @field_validator("vision_model", "caption_model")
    @classmethod
    def validate_model_names(cls, v: str) -> str:
        """Validate that model names are reasonable OpenAI model identifiers"""
        valid_prefixes = ("gpt-4", "gpt-3.5", "o1", "o3")
        if not any(v.startswith(prefix) for prefix in valid_prefixes):
            raise ValueError(f"Model '{v}' does not appear to be a valid OpenAI model")
        return v
    
    def model_post_init(self, __context) -> None:
        """Handle legacy 'model' field for backward compatibility"""
        # This method is called after __init__ but validation has already happened
        # The config loader handles the legacy model field, so this is just for documentation
        pass


class PlatformsConfig(BaseModel):
    telegram_enabled: bool = False
    instagram_enabled: bool = False
    email_enabled: bool = False


class TelegramConfig(BaseModel):
    # In orchestrator mode, bot_token may be resolved lazily; env-loader still requires it.
    bot_token: Optional[str] = Field(default=None, description="Telegram bot token")
    channel_id: str = Field(..., description="Telegram channel/chat id")


class InstagramConfig(BaseModel):
    username: str = Field(..., description="Instagram username")
    password: str = Field(..., description="Instagram password (instagrapi, optional in V2)")
    session_file: str = Field(default="instasession.json", description="Session file path")


class EmailConfig(BaseModel):
    sender: str = Field(..., description="Sender email address")
    recipient: str = Field(..., description="Recipient email address")
    # In orchestrator mode, password may be resolved lazily; env-loader still requires it.
    password: Optional[str] = Field(default=None, description="Email (app) password")
    smtp_server: str = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=587)
    # Confirmation email back to sender after service email is sent
    confirmation_to_sender: bool = Field(default=True, description="Send a confirmation email to sender")
    confirmation_tags_count: int = Field(default=5, description="How many descriptive tags to include in confirmation")
    confirmation_tags_nature: str = Field(
        default="short, lowercase, human-friendly topical nouns; no hashtags; no emojis",
        description="Guidance for how tags should look in the confirmation email",
    )
    # Where to place the caption for email-based services (FetLife expects subject)
    caption_target: str = Field(
        default="subject",
        description="Where to place the caption: subject | body | both",
    )
    # Optional subject prefix per FetLife rules: Private:/Avatar:/normal
    subject_mode: str = Field(
        default="normal",
        description="Subject mode/prefix: normal | private | avatar",
    )

    @field_validator("caption_target")
    @classmethod
    def validate_caption_target(cls, v: str) -> str:
        allowed = {"subject", "body", "both"}
        v2 = v.strip().lower()
        if v2 not in allowed:
            raise ValueError(f"caption_target must be one of {allowed}")
        return v2

    @field_validator("subject_mode")
    @classmethod
    def validate_subject_mode(cls, v: str) -> str:
        allowed = {"normal", "private", "avatar"}
        v2 = v.strip().lower()
        if v2 not in allowed:
            raise ValueError(f"subject_mode must be one of {allowed}")
        return v2


class ContentConfig(BaseModel):
    hashtag_string: str = Field(default="", description="Hashtags to append")
    archive: bool = Field(default=True, description="Archive after posting")
    debug: bool = Field(default=False, description="Debug mode")


class CaptionFileConfig(BaseModel):
    """
    Configuration for caption sidecar files.
    - extended_metadata_enabled controls Phase 2 contextual metadata output.
    Phase 1 identity/version metadata is always included when sd_caption exists.
    """
    extended_metadata_enabled: bool = Field(
        default=False,
        description="Enable Phase 2 extended contextual metadata (pose, lighting, materials, art_style, tags, moderation)",
    )
    artist_alias: Optional[str] = Field(
        default=None,
        description="Artist/photographer alias to include in caption file metadata",
    )


class FeaturesConfig(BaseModel):
    analyze_caption_enabled: bool = Field(
        default=True,
        description="Enable AI vision analysis and caption generation feature",
    )
    publish_enabled: bool = Field(
        default=True,
        description="Enable publishing feature (all platforms)",
    )
    keep_enabled: bool = Field(
        default=True,
        description="Enable Keep curation action in web/CLI flows",
    )
    remove_enabled: bool = Field(
        default=True,
        description="Enable Remove curation action in web/CLI flows",
    )
    auto_view_enabled: bool = Field(
        default=False,
        description="Allow random images to be viewed without admin login in the web UI",
    )


class WebConfig(BaseModel):
    """
    Optional configuration for the web interface.
    For MVP we primarily rely on environment variables, but this model
    allows typed access and future INI-based overrides.
    """

    enabled: bool = Field(
        default=False,
        description="Enable the web interface",
    )
    host: str = Field(
        default="0.0.0.0",
        description="Host interface for the web server",
    )
    port: int = Field(
        default=8000,
        description="Port for the web server when run directly (Heroku sets PORT env)",
    )
    auth_enabled: bool = Field(
        default=True,
        description="Require authentication for mutating web API actions",
    )
    auth_token: Optional[str] = Field(
        default=None,
        description="Optional bearer token for API auth",
    )
    auth_user: Optional[str] = Field(
        default=None,
        description="Optional basic auth username for API auth",
    )
    auth_pass: Optional[str] = Field(
        default=None,
        description="Optional basic auth password for API auth",
    )
    admin_cookie_ttl_seconds: int = Field(
        default=3600,
        description="TTL for admin-mode cookie in seconds (MVP default ~1h)",
    )


class Auth0Config(BaseModel):
    """
    Configuration for Auth0 OIDC integration.
    Loaded primarily from AUTH0_* environment variables.
    """
    domain: str = Field(..., description="Auth0 domain (e.g. tenant.auth0.com)")
    client_id: str = Field(..., description="Auth0 Client ID")
    client_secret: str = Field(..., description="Auth0 Client Secret")
    audience: Optional[str] = Field(default=None, description="Auth0 API Audience (optional)")
    callback_url: str = Field(..., description="Full callback URL (e.g. https://app.com/api/auth/callback)")
    admin_emails: str = Field(..., description="Comma-separated list of allowed emails")

    @property
    def admin_emails_list(self) -> list[str]:
        """Parse admin_emails CSV string into a list of emails, stripping whitespace."""
        if not self.admin_emails:
            return []
        return [e.strip() for e in self.admin_emails.split(",") if e.strip()]


class ApplicationConfig(BaseModel):
    dropbox: DropboxConfig
    openai: OpenAIConfig
    platforms: PlatformsConfig
    features: FeaturesConfig = FeaturesConfig()
    telegram: Optional[TelegramConfig] = None
    instagram: Optional[InstagramConfig] = None
    email: Optional[EmailConfig] = None
    content: ContentConfig
    captionfile: CaptionFileConfig = CaptionFileConfig()
    web: WebConfig = WebConfig()
    auth0: Optional[Auth0Config] = None



