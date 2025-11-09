from __future__ import annotations

from pydantic import BaseModel, Field, field_validator
from typing import Optional


class DropboxConfig(BaseModel):
    app_key: str = Field(..., description="Dropbox application key")
    app_secret: str = Field(..., description="Dropbox application secret")
    refresh_token: str = Field(..., description="OAuth2 refresh token")
    image_folder: str = Field(..., description="Source image folder path in Dropbox")
    archive_folder: str = Field(default="archive", description="Archive folder name (relative)")

    @field_validator("image_folder")
    @classmethod
    def validate_folder_path(cls, v: str) -> str:
        if not v.startswith("/"):
            raise ValueError("Dropbox folder path must start with /")
        return v


class OpenAIConfig(BaseModel):
    api_key: str = Field(..., description="OpenAI API key")
    
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
    def validate_api_key(cls, v: str) -> str:
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
    bot_token: str = Field(..., description="Telegram bot token")
    channel_id: str = Field(..., description="Telegram channel/chat id")


class InstagramConfig(BaseModel):
    username: str = Field(..., description="Instagram username")
    password: str = Field(..., description="Instagram password (instagrapi, optional in V2)")
    session_file: str = Field(default="instasession.json", description="Session file path")


class EmailConfig(BaseModel):
    sender: str = Field(..., description="Sender email address")
    recipient: str = Field(..., description="Recipient email address")
    password: str = Field(..., description="Email (app) password")
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


class ApplicationConfig(BaseModel):
    dropbox: DropboxConfig
    openai: OpenAIConfig
    platforms: PlatformsConfig
    telegram: Optional[TelegramConfig] = None
    instagram: Optional[InstagramConfig] = None
    email: Optional[EmailConfig] = None
    content: ContentConfig
    captionfile: CaptionFileConfig = CaptionFileConfig()


