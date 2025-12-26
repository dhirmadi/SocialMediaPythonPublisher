from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class OrchestratorFeatures(BaseModel):
    model_config = ConfigDict(extra="allow")

    publish_enabled: bool = False
    analyze_caption_enabled: bool = False
    keep_enabled: bool = True
    remove_enabled: bool = True
    auto_view_enabled: bool = False


class OrchestratorStoragePaths(BaseModel):
    model_config = ConfigDict(extra="allow")

    root: str
    archive: Optional[str] = None
    keep: Optional[str] = None
    remove: Optional[str] = None


class OrchestratorStorage(BaseModel):
    model_config = ConfigDict(extra="allow")

    provider: str
    credentials_ref: str
    paths: OrchestratorStoragePaths


class OrchestratorPublisher(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    type: str
    enabled: bool = True
    credentials_ref: Optional[str] = None
    config: dict[str, Any] = Field(default_factory=dict)


class OrchestratorEmailServer(BaseModel):
    model_config = ConfigDict(extra="allow")

    host: str
    port: int = 587
    use_tls: bool = True
    from_email: str
    username: Optional[str] = None
    password_ref: Optional[str] = None


class OrchestratorAI(BaseModel):
    model_config = ConfigDict(extra="allow")

    credentials_ref: Optional[str] = None
    vision_model: Optional[str] = None
    caption_model: Optional[str] = None
    system_prompt: Optional[str] = None
    role_prompt: Optional[str] = None
    sd_caption_enabled: Optional[bool] = None
    sd_caption_single_call_enabled: Optional[bool] = None
    sd_caption_model: Optional[str] = None
    sd_caption_system_prompt: Optional[str] = None
    sd_caption_role_prompt: Optional[str] = None


class OrchestratorCaptionFile(BaseModel):
    model_config = ConfigDict(extra="allow")

    extended_metadata_enabled: Optional[bool] = None
    artist_alias: Optional[str] = None


class OrchestratorConfirmation(BaseModel):
    model_config = ConfigDict(extra="allow")

    confirmation_to_sender: Optional[bool] = None
    confirmation_tags_count: Optional[int] = None
    confirmation_tags_nature: Optional[str] = None


class OrchestratorContent(BaseModel):
    model_config = ConfigDict(extra="allow")

    hashtag_string: Optional[str] = None
    archive: Optional[bool] = None
    debug: Optional[bool] = None


class OrchestratorConfigV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    features: OrchestratorFeatures
    storage: OrchestratorStorage


class OrchestratorConfigV2(OrchestratorConfigV1):
    model_config = ConfigDict(extra="allow")

    publishers: list[OrchestratorPublisher] = Field(default_factory=list)
    email_server: Optional[OrchestratorEmailServer] = None
    ai: Optional[OrchestratorAI] = None
    captionfile: Optional[OrchestratorCaptionFile] = None
    confirmation: Optional[OrchestratorConfirmation] = None
    content: Optional[OrchestratorContent] = None


class OrchestratorRuntimeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    tenant: str
    app_type: str
    config_version: str
    ttl_seconds: int = 600
    config: dict[str, Any]


