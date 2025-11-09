from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional
import os


@dataclass
class Image:
    filename: str
    dropbox_path: str
    sha256: Optional[str] = None
    temp_link: Optional[str] = None
    local_path: Optional[str] = None
    size_bytes: Optional[int] = None
    format: Optional[str] = None

    @property
    def extension(self) -> str:
        return os.path.splitext(self.filename)[1]


@dataclass
class ImageAnalysis:
    description: str
    mood: str
    tags: List[str] = field(default_factory=list)
    nsfw: bool = False
    safety_labels: List[str] = field(default_factory=list)
    sd_caption: Optional[str] = None


@dataclass
class CaptionSpec:
    platform: str
    style: str
    hashtags: str
    max_length: int


@dataclass
class PublishResult:
    success: bool
    platform: str
    post_id: Optional[str] = None
    error: Optional[str] = None


@dataclass
class WorkflowResult:
    success: bool
    image_name: str
    caption: str
    publish_results: Dict[str, PublishResult]
    archived: bool
    error: Optional[str] = None
    correlation_id: Optional[str] = None
    finished_at: datetime = field(default_factory=datetime.utcnow)
    # Preview mode fields
    image_analysis: Optional[ImageAnalysis] = None
    caption_spec: Optional[CaptionSpec] = None
    dropbox_url: Optional[str] = None
    sha256: Optional[str] = None
    image_folder: Optional[str] = None


