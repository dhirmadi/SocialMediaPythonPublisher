from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class OrchestratorAuth(BaseModel):
    """
    Tenant-scoped auth/authorization metadata delivered in schema v2 runtime config.

    Notes:
    - No secrets should ever be included here (no Auth0 client_secret).
    - Publisher treats this primarily as an authorization allowlist + enable/disable flag.
    """

    model_config = ConfigDict(extra="allow")

    provider: str | None = None
    enabled: bool = False
    domain: str | None = None
    client_id: str | None = None
    audience: str | None = None
    allowed_emails: list[str] = Field(default_factory=list)


class OrchestratorFeatures(BaseModel):
    model_config = ConfigDict(extra="allow")

    publish_enabled: bool = False
    analyze_caption_enabled: bool = False
    keep_enabled: bool = True
    remove_enabled: bool = True
    auto_view_enabled: bool = False
    alt_text_enabled: bool = True
    smart_hashtags_enabled: bool = True
    voice_matching_enabled: bool = False


class OrchestratorStoragePaths(BaseModel):
    model_config = ConfigDict(extra="allow")

    root: str
    archive: str | None = None
    keep: str | None = None
    remove: str | None = None


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
    credentials_ref: str | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class OrchestratorEmailServer(BaseModel):
    model_config = ConfigDict(extra="allow")

    host: str
    port: int = 587
    use_tls: bool = True
    from_email: str
    username: str | None = None
    password_ref: str | None = None


class OrchestratorAI(BaseModel):
    model_config = ConfigDict(extra="allow")

    credentials_ref: str | None = None
    vision_model: str | None = None
    caption_model: str | None = None
    system_prompt: str | None = None
    role_prompt: str | None = None
    sd_caption_enabled: bool | None = None
    sd_caption_single_call_enabled: bool | None = None
    sd_caption_model: str | None = None
    sd_caption_system_prompt: str | None = None
    sd_caption_role_prompt: str | None = None
    vision_model_lifecycle: dict[str, Any] | None = None
    caption_model_lifecycle: dict[str, Any] | None = None


class OrchestratorCaptionFile(BaseModel):
    model_config = ConfigDict(extra="allow")

    extended_metadata_enabled: bool | None = None
    artist_alias: str | None = None


class OrchestratorConfirmation(BaseModel):
    model_config = ConfigDict(extra="allow")

    confirmation_to_sender: bool | None = None
    confirmation_tags_count: int | None = None
    confirmation_tags_nature: str | None = None


class OrchestratorContent(BaseModel):
    model_config = ConfigDict(extra="allow")

    hashtag_string: str | None = None
    archive: bool | None = None
    debug: bool | None = None
    voice_profile: list[str] | None = None


class OrchestratorConfigV1(BaseModel):
    model_config = ConfigDict(extra="allow")

    features: OrchestratorFeatures
    storage: OrchestratorStorage


class OrchestratorConfigV2(OrchestratorConfigV1):
    model_config = ConfigDict(extra="allow")

    auth: OrchestratorAuth | None = None
    publishers: list[OrchestratorPublisher] = Field(default_factory=list)
    email_server: OrchestratorEmailServer | None = None
    ai: OrchestratorAI | None = None
    captionfile: OrchestratorCaptionFile | None = None
    confirmation: OrchestratorConfirmation | None = None
    content: OrchestratorContent | None = None


class OrchestratorRuntimeResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: int = 1
    tenant: str
    app_type: str
    config_version: str
    ttl_seconds: int = 600
    config: dict[str, Any]
