from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from publisher_v2.config.schema import ApplicationConfig


@dataclass(frozen=True, slots=True)
class Image:
    filename: str
    dropbox_path: str
    sha256: str | None = None
    temp_link: str | None = None
    local_path: str | None = None
    size_bytes: int | None = None
    format: str | None = None

    @property
    def extension(self) -> str:
        return os.path.splitext(self.filename)[1]


@dataclass(frozen=True, slots=True)
class ImageAnalysis:
    description: str
    mood: str
    tags: list[str] = field(default_factory=list)
    nsfw: bool = False
    safety_labels: list[str] = field(default_factory=list)
    sd_caption: str | None = None
    # Optional detailed fields for richer analysis (backward-compatible)
    subject: str | None = None
    style: str | None = None
    lighting: str | None = None
    camera: str | None = None
    clothing_or_accessories: str | None = None
    aesthetic_terms: list[str] = field(default_factory=list)
    pose: str | None = None
    composition: str | None = None
    background: str | None = None
    color_palette: str | None = None


@dataclass(frozen=True, slots=True)
class CaptionSpec:
    platform: str
    style: str
    hashtags: str
    max_length: int

    @staticmethod
    def for_config(config: ApplicationConfig) -> CaptionSpec:
        """Build the appropriate CaptionSpec based on platform configuration."""
        if config.platforms.email_enabled and config.email:
            return CaptionSpec(
                platform="fetlife_email",
                style="engagement_question",
                hashtags="",
                max_length=240,
            )
        return CaptionSpec(
            platform="generic",
            style="minimal_poetic",
            hashtags=config.content.hashtag_string,
            max_length=2200,
        )


@dataclass(frozen=True, slots=True)
class PublishResult:
    success: bool
    platform: str
    post_id: str | None = None
    error: str | None = None


@dataclass(frozen=True, slots=True)
class WorkflowResult:
    success: bool
    image_name: str
    caption: str
    publish_results: dict[str, PublishResult]
    archived: bool
    error: str | None = None
    correlation_id: str | None = None
    finished_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    # Preview mode fields
    image_analysis: ImageAnalysis | None = None
    caption_spec: CaptionSpec | None = None
    dropbox_url: str | None = None
    sha256: str | None = None
    image_folder: str | None = None
