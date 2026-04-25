from typing import Any

from pydantic import BaseModel


class ImageListResponse(BaseModel):
    filenames: list[str]
    count: int


class ImageResponse(BaseModel):
    filename: str
    temp_url: str
    thumbnail_url: str | None = None
    sha256: str | None = None
    caption: str | None = None
    sd_caption: str | None = None
    metadata: dict[str, Any] | None = None
    has_sidecar: bool


class AnalysisResponse(BaseModel):
    filename: str
    description: str
    mood: str
    tags: list[str]
    nsfw: bool
    caption: str
    sd_caption: str | None = None
    alt_text: str | None = None
    sidecar_written: bool
    platform_captions: dict[str, str] | None = None


class PublishRequest(BaseModel):
    platforms: list[str] | None = None
    caption: str | None = None


class PublishResponse(BaseModel):
    filename: str
    results: dict[str, dict[str, Any]]
    archived: bool
    any_success: bool


class ErrorResponse(BaseModel):
    error: str
    detail: str | None = None


class AdminLoginRequest(BaseModel):
    password: str


class AdminStatusResponse(BaseModel):
    admin: bool
    error: str | None = None


class CurationResponse(BaseModel):
    filename: str
    action: str  # "keep" or "remove"
    destination_folder: str
    preview_only: bool = False
