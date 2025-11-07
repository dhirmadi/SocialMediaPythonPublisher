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
    model: str = Field(default="gpt-4o-mini", description="OpenAI model for captioning/vision")
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


class ContentConfig(BaseModel):
    hashtag_string: str = Field(default="", description="Hashtags to append")
    archive: bool = Field(default=True, description="Archive after posting")
    debug: bool = Field(default=False, description="Debug mode")


class ApplicationConfig(BaseModel):
    dropbox: DropboxConfig
    openai: OpenAIConfig
    platforms: PlatformsConfig
    telegram: Optional[TelegramConfig] = None
    instagram: Optional[InstagramConfig] = None
    email: Optional[EmailConfig] = None
    content: ContentConfig


