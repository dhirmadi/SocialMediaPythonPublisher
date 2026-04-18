import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from publisher_v2.config.schema import ApplicationConfig


@dataclass(frozen=True, slots=True)
class AIUsage:
    response_id: str
    total_tokens: int
    prompt_tokens: int
    completion_tokens: int


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
    def for_platforms(config: "ApplicationConfig") -> dict[str, "CaptionSpec"]:
        """Build a CaptionSpec per enabled publisher.

        Style directives come from the platform_captions registry in ai_prompts.yaml.
        Falls back to 'generic' for unknown platforms.
        """
        from publisher_v2.config.static_loader import get_static_config

        registry = get_static_config().ai_prompts.platform_captions
        generic = registry.get("generic")

        specs: dict[str, CaptionSpec] = {}

        platform_enabled = {
            "telegram": config.platforms.telegram_enabled,
            "instagram": config.platforms.instagram_enabled,
            "email": config.platforms.email_enabled,
        }

        for name, enabled in platform_enabled.items():
            if enabled:
                style_cfg = registry.get(name, generic)
                if style_cfg is None:
                    continue
                hashtags = config.content.hashtag_string if style_cfg.hashtags else ""
                specs[name] = CaptionSpec(
                    platform=name,
                    style=style_cfg.style,
                    hashtags=hashtags,
                    max_length=style_cfg.max_length,
                )

        if not specs:
            # No enabled publishers — return generic
            fallback = generic
            if fallback:
                specs["generic"] = CaptionSpec(
                    platform="generic",
                    style=fallback.style,
                    hashtags=config.content.hashtag_string,
                    max_length=fallback.max_length,
                )
            else:
                specs["generic"] = CaptionSpec(
                    platform="generic",
                    style="minimal_poetic",
                    hashtags=config.content.hashtag_string,
                    max_length=2200,
                )

        return specs

    @staticmethod
    def for_config(config: "ApplicationConfig") -> "CaptionSpec":
        """Build the appropriate CaptionSpec based on platform configuration.

        Deprecated: use for_platforms() for multi-platform generation.
        Preserved for backwards compatibility with web/service.py and existing tests.
        """
        specs = CaptionSpec.for_platforms(config)
        # Return the first spec (or generic)
        return next(iter(specs.values()))


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
    platform_captions: dict[str, str] = field(default_factory=dict)
    # Preview mode fields
    image_analysis: ImageAnalysis | None = None
    caption_spec: CaptionSpec | None = None
    dropbox_url: str | None = None
    sha256: str | None = None
    image_folder: str | None = None
