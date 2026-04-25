from pydantic import BaseModel, Field, field_validator, model_validator


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


class StoragePathConfig(BaseModel):
    """Provider-agnostic storage paths. Works for both Dropbox and managed storage."""

    image_folder: str = Field(..., description="Root path for images")
    archive_folder: str = Field(default="archive", description="Archive path")
    folder_keep: str | None = Field(default="keep", description="Keep subfolder")
    folder_remove: str | None = Field(default="reject", description="Remove subfolder")


class ManagedStorageConfig(BaseModel):
    """S3-compatible managed storage configuration (Cloudflare R2, AWS S3, MinIO)."""

    access_key_id: str = Field(..., description="S3 access key ID")
    secret_access_key: str = Field(..., description="S3 secret access key")
    endpoint_url: str = Field(..., description="S3-compatible endpoint URL")
    bucket: str = Field(..., description="S3 bucket name")
    region: str = Field(default="auto", description="S3 region")


class ModelLifecycle(BaseModel):
    """Advisory lifecycle metadata for an OpenAI model (PUB-040)."""

    warning: str
    shutdown_date: str
    recommended_replacement: str
    severity: str

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        allowed = {"info", "warning", "critical"}
        if v not in allowed:
            raise ValueError(f"severity must be one of {allowed}, got '{v}'")
        return v


class OpenAIConfig(BaseModel):
    # In orchestrator mode, api_key may be resolved lazily; loader still requires it.
    api_key: str | None = Field(default=None, description="OpenAI API key")

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
    sd_caption_model: str | None = Field(
        default=None,
        description="Optional override model for SD caption single-call generation",
    )
    sd_caption_system_prompt: str | None = Field(
        default=None,
        description="Optional system prompt override for SD caption generation",
    )
    sd_caption_role_prompt: str | None = Field(
        default=None,
        description="Optional role/user prompt override for SD caption generation",
    )

    # Deprecated: kept for backward compatibility
    model: str | None = Field(
        default=None,
        description="(Deprecated) Single model for both tasks. Use vision_model and caption_model instead.",
    )

    system_prompt: str = Field(
        default="You are a senior social media copywriter. Write authentic, concise, platform-aware captions.",
        description="System prompt used for caption generation",
    )
    role_prompt: str = Field(default="Write a caption for:", description="Role/user prompt prefix")

    # PUB-040: Advisory lifecycle metadata (observability only)
    vision_model_lifecycle: ModelLifecycle | None = Field(
        default=None, description="Advisory lifecycle metadata for vision model"
    )
    caption_model_lifecycle: ModelLifecycle | None = Field(
        default=None, description="Advisory lifecycle metadata for caption model"
    )

    # PUB-041: Vision cost optimization
    vision_max_dimension: int = Field(
        default=1024,
        description="Longest side in pixels for vision input. 0 disables resize (legacy: send presigned URL).",
    )
    vision_detail: str = Field(
        default="low",
        description="OpenAI vision 'detail' parameter (low|high|auto).",
    )
    vision_fallback_enabled: bool = Field(
        default=True,
        description="Escalate to higher quality vision call when the cheap path fails.",
    )
    vision_fallback_max_dimension: int = Field(
        default=2048,
        description="Longest side in pixels for the fallback vision call. 0 disables resize on fallback.",
    )
    vision_fallback_detail: str = Field(
        default="high",
        description="OpenAI vision 'detail' parameter for the fallback call (low|high|auto).",
    )

    @field_validator("vision_detail", "vision_fallback_detail")
    @classmethod
    def validate_vision_detail(cls, v: str) -> str:
        allowed = {"low", "high", "auto"}
        if v not in allowed:
            raise ValueError(f"vision detail must be one of {allowed}, got '{v}'")
        return v

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str | None) -> str | None:
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
    bot_token: str | None = Field(default=None, description="Telegram bot token")
    channel_id: str = Field(..., description="Telegram channel/chat id")


class InstagramConfig(BaseModel):
    username: str = Field(..., description="Instagram username")
    password: str = Field(..., description="Instagram password (instagrapi, optional in V2)")
    session_file: str = Field(default="instasession.json", description="Session file path")


class EmailConfig(BaseModel):
    sender: str = Field(..., description="Sender email address")
    recipient: str = Field(..., description="Recipient email address")
    # In orchestrator mode, password may be resolved lazily; env-loader still requires it.
    password: str | None = Field(default=None, description="Email (app) password")
    smtp_server: str = Field(default="smtp.gmail.com")
    smtp_port: int = Field(default=587)
    # Confirmation after service email is sent (recipients: admin login emails when configured, else SMTP sender)
    confirmation_to_sender: bool = Field(
        default=True,
        description="Send a confirmation copy; recipients are Auth0 admin allowlist emails when set, else sender",
    )
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
    voice_profile: list[str] | None = Field(default=None, description="Operator example captions for few-shot tone")

    @field_validator("voice_profile")
    @classmethod
    def validate_voice_profile(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        if len(v) > 20:
            raise ValueError("voice_profile may contain at most 20 examples")
        if any(not s.strip() for s in v):
            raise ValueError("voice_profile entries must be non-empty strings")
        return v


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
    artist_alias: str | None = Field(
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
    delete_enabled: bool = Field(
        default=False,
        description="Enable permanent delete button in image review workflow (admin only)",
    )
    auto_view_enabled: bool = Field(
        default=False,
        description="Allow random images to be viewed without admin login in the web UI",
    )
    library_enabled: bool = Field(
        default=False,
        description="Enable admin library management panel (auto-enabled for managed storage instances)",
    )
    alt_text_enabled: bool = Field(default=True, description="Enable AI alt-text generation (PUB-026)")
    smart_hashtags_enabled: bool = Field(default=True, description="Enable smart hashtag generation (PUB-028)")
    voice_matching_enabled: bool = Field(
        default=False, description="Enable voice profile injection for caption tone matching"
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
    auth_token: str | None = Field(
        default=None,
        description="Optional bearer token for API auth",
    )
    auth_user: str | None = Field(
        default=None,
        description="Optional basic auth username for API auth",
    )
    auth_pass: str | None = Field(
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
    audience: str | None = Field(default=None, description="Auth0 API Audience (optional)")
    callback_url: str | None = Field(
        default=None,
        description="Optional static callback URL fallback (dynamic callback is derived from request Host)",
    )
    admin_emails: str = Field(
        default="",
        description=(
            "Comma-separated list of allowed emails. In orchestrator mode, this may be "
            "overridden per-tenant from runtime config (auth.allowed_emails)."
        ),
    )

    @property
    def admin_emails_list(self) -> list[str]:
        """Parse admin_emails CSV string into a list of emails, stripping whitespace."""
        if not self.admin_emails:
            return []
        return [e.strip() for e in self.admin_emails.split(",") if e.strip()]


class ApplicationConfig(BaseModel):
    dropbox: DropboxConfig | None = None
    managed: ManagedStorageConfig | None = None
    storage_paths: StoragePathConfig
    openai: OpenAIConfig
    platforms: PlatformsConfig
    features: FeaturesConfig = FeaturesConfig()
    telegram: TelegramConfig | None = None
    instagram: InstagramConfig | None = None
    email: EmailConfig | None = None
    content: ContentConfig
    captionfile: CaptionFileConfig = CaptionFileConfig()
    web: WebConfig = WebConfig()
    auth0: Auth0Config | None = None

    @model_validator(mode="after")
    def validate_storage_provider(self) -> "ApplicationConfig":
        if self.dropbox is None and self.managed is None:
            raise ValueError("Exactly one storage provider must be set: dropbox or managed")
        if self.dropbox is not None and self.managed is not None:
            raise ValueError("Only one storage provider can be set: dropbox or managed (not both)")
        return self
