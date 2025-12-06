from __future__ import annotations

from typing import Optional, Dict, Any, List

from pydantic import BaseModel


class ImageResponse(BaseModel):
    filename: str
    temp_url: str
    thumbnail_url: Optional[str] = None
    sha256: Optional[str] = None
    caption: Optional[str] = None
    sd_caption: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    has_sidecar: bool


class AnalysisResponse(BaseModel):
    filename: str
    description: str
    mood: str
    tags: List[str]
    nsfw: bool
    caption: str
    sd_caption: Optional[str] = None
    sidecar_written: bool


class PublishRequest(BaseModel):
    platforms: Optional[List[str]] = None


class PublishResponse(BaseModel):
    filename: str
    results: Dict[str, Dict[str, Any]]
    archived: bool
    any_success: bool


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None


class AdminLoginRequest(BaseModel):
    password: str


class AdminStatusResponse(BaseModel):
    admin: bool
    error: Optional[str] = None


class CurationResponse(BaseModel):
    filename: str
    action: str  # "keep" or "remove"
    destination_folder: str
    preview_only: bool = False

