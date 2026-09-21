"""Static (non-secret, repo-versioned) configuration loaded from YAML.

Holds the prompt text, per-platform caption styles and limits, preview/web-UI
strings and service limits that ship with the app. Every file is optional: a
missing or malformed YAML file warns and the built-in defaults below apply, so
the app always starts. ``PV2_STATIC_CONFIG_DIR`` overrides the directory
fleet-wide. Tenant-specific values live in runtime config, not here.
"""

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from publisher_v2.utils.logging import log_json

logger = logging.getLogger("publisher_v2.config.static")


class AIVisionPrompts(BaseModel):
    """Prompt pair driving OpenAI Vision image analysis."""

    system: str | None = Field(
        default=None,
        description="System prompt for vision analysis",
    )
    user: str | None = Field(
        default=None,
        description="User instructions for vision analysis",
    )


class AICaptionPrompts(BaseModel):
    """Default caption prompts, layered with tenant settings.

    A tenant ``system_prompt`` replaces ``system`` outright, while ``rules`` is
    appended to whichever persona ends up in force (#138).
    """

    system: str | None = Field(
        default=None,
        description="Caption persona. A tenant system_prompt replaces this entirely",
    )
    rules: str | None = Field(
        default=None,
        description="Appended to whichever persona is in force, tenant or default (#138)",
    )
    role: str | None = Field(
        default=None,
        description="Role/user prompt template for caption generation (multi-platform)",
    )
    role_single: str | None = Field(
        default=None,
        description="Role prompt used when only one platform is being written (#138)",
    )


class AISDCaptionPrompts(BaseModel):
    """Prompts for generating Stable-Diffusion-style descriptive captions."""

    system: str | None = Field(
        default=None,
        description="System prompt for SD caption generation",
    )
    role: str | None = Field(
        default=None,
        description="Role/user prompt template for SD caption generation",
    )


class PlatformCaptionStyle(BaseModel):
    """Per-platform caption shaping: style directive, length cap, hashtags, closing.

    Unknown keys are ignored rather than rejected, and a reintroduced
    ``examples`` key is stripped with a warning — see ``_strip_static_examples``.
    """

    # #138: no static example captions ship with the app — the tenant
    # voice_profile is the only source of examples.
    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _strip_static_examples(cls, data: Any) -> Any:
        """Drop a reintroduced ``examples`` key, loudly, instead of refusing to start.

        PV2_STATIC_CONFIG_DIR is a fleet-wide override: an operator pointing at
        a directory written before #138 would otherwise take every instance
        down — the CLI at generator construction, the web app inside its
        lifespan, so even ``GET /`` 500s. Malformed YAML in the same file warns
        and falls back to defaults, and an unsupported key is a smaller problem
        than that. The examples do not reach a prompt either way.
        """
        if isinstance(data, dict) and data.get("examples"):
            data = {k: v for k, v in data.items() if k != "examples"}
            log_json(
                logger,
                logging.WARNING,
                "static_caption_examples_ignored",
                reason="static example captions are not supported; use the tenant voice_profile (#138)",
            )
        return data

    style: str = Field(default="minimal_poetic", description="Caption style directive for this platform")
    max_length: int = Field(default=2200, description="Maximum caption length")
    hashtags: bool = Field(default=True, description="Whether to include hashtags")
    guidance: str = Field(default="", max_length=1000, description="Platform length/register brief")
    closing: Literal["question", "statement", "any"] = Field(
        default="any",
        description="Mandated closing; when set, the closing-pattern-to-avoid constraint is skipped",
    )


class ConfirmationTagsConfig(BaseModel):
    """Prompt and default count for the confirmation tags offered after analysis."""

    prompt: str = Field(
        default="short, lowercase, human-friendly topical nouns; no hashtags; no emojis",
        description="Prompt for confirmation tags generation",
    )
    default_count: int = Field(
        default=5,
        description="Default number of confirmation tags to generate",
    )


class CaptionHistoryConfig(BaseModel):
    """Bounds on the recent-caption history fed back into the caption prompt."""

    # #82: reduced from 8 — history feeds the prompt as constraints, and a
    # small window keeps the openings-to-avoid list tight.
    window_size: int = Field(default=3, ge=0, le=50, description="Number of recent captions to fetch")
    max_tokens_budget: int = Field(default=1000, ge=0, le=10000, description="Max tokens for history context")


class AIPromptsConfig(BaseModel):
    """Root of ai_prompts.yaml: every prompt and caption-style default.

    ``platform_captions`` is a registry keyed by platform name; a tenant adding
    a platform key here gets that style without a code change, and unknown
    platforms fall back to the ``generic`` entry.
    """

    vision: AIVisionPrompts = AIVisionPrompts()
    caption: AICaptionPrompts = AICaptionPrompts()
    sd_caption: AISDCaptionPrompts = AISDCaptionPrompts()
    confirmation_tags: ConfirmationTagsConfig = ConfirmationTagsConfig()
    platform_captions: dict[str, PlatformCaptionStyle] = Field(
        default_factory=lambda: {
            "telegram": PlatformCaptionStyle(
                style="conversational, emoji-friendly, artistic commentary", max_length=4096, hashtags=True
            ),
            "instagram": PlatformCaptionStyle(
                style="hook-first, hashtags woven naturally, engaging, visual storytelling",
                max_length=2200,
                hashtags=True,
            ),
            "email": PlatformCaptionStyle(
                style="intimate, FetLife-appropriate",
                max_length=240,
                hashtags=False,
                guidance="FetLife email subject. 30 to 35 words, one moment, first person, no hashtags.",
            ),
            "generic": PlatformCaptionStyle(style="minimal_poetic", max_length=2200, hashtags=True),
        },
        description="Per-platform caption style registry",
    )
    caption_history: CaptionHistoryConfig = CaptionHistoryConfig()


class PlatformLimit(BaseModel):
    """Hard publishing limits for one platform.

    Every field is optional: None means "this platform imposes no such limit"
    and the corresponding enforcement step is skipped. ``caption_target`` and
    ``subject_mode`` apply to the email/FetLife publisher only.
    """

    max_caption_length: int | None = Field(
        default=None,
        description="Maximum caption length for this platform",
    )
    max_hashtags: int | None = Field(
        default=None,
        description="Maximum number of hashtags for this platform",
    )
    resize_width_px: int | None = Field(
        default=None,
        description="Maximum resize width in pixels for this platform",
    )
    # Email/FetLife-specific settings
    caption_target: str | None = Field(
        default=None,
        description="Where to place caption: subject | body | both",
    )
    subject_mode: str | None = Field(
        default=None,
        description="Subject prefix mode: normal | private | avatar",
    )


class PlatformLimitsConfig(BaseModel):
    """Root of platform_limits.yaml — the per-platform limits actually enforced at publish time."""

    instagram: PlatformLimit = PlatformLimit(
        max_caption_length=2200,
        max_hashtags=30,
        resize_width_px=1080,
    )
    telegram: PlatformLimit = PlatformLimit(
        max_caption_length=4096,
        resize_width_px=1280,
    )
    email: PlatformLimit = PlatformLimit(
        max_caption_length=240,
        caption_target="subject",
        subject_mode="normal",
    )
    generic: PlatformLimit = PlatformLimit(
        max_caption_length=2200,
    )


class PreviewTextConfig(BaseModel):
    """Section headers and messages printed by the side-effect-free CLI preview."""

    headers: dict[str, str] = Field(
        default_factory=lambda: {
            "preview_mode": "PUBLISHER V2 - PREVIEW MODE",
            "image_selected": "📸 IMAGE SELECTED",
            "vision_analysis": "🔍 AI VISION ANALYSIS",
            "caption_generation": "✍️  AI CAPTION GENERATION",
            "publishing_preview": "📤 PUBLISHING PREVIEW",
            "email_confirmation": "✉️  EMAIL CONFIRMATION",
            "configuration": "⚙️  CONFIGURATION",
            "preview_footer": "⚠️  PREVIEW MODE - NO ACTIONS TAKEN",
        }
    )
    messages: dict[str, str] = Field(
        default_factory=lambda: {
            "no_caption_yet": "No caption yet.",
            "analysis_skipped": "⚠ Analysis skipped (FEATURE_ANALYZE_CAPTION=false)",
            "publish_disabled": "⚠ Publish feature disabled (FEATURE_PUBLISH=false). No platforms will be contacted.",
        }
    )


class WebUITextConfig(BaseModel):
    """Localizable web-UI strings (titles, buttons, panels, placeholders, status).

    Loaded from web_ui_text.en.yaml and kept as a free-form nested mapping so
    the single-page front end can read new keys without a schema change here.
    """

    values: dict[str, Any] = Field(
        default_factory=lambda: {
            "title": "Publisher V2 Web",
            "header_title": "Publisher V2 Web",
            "buttons": {
                "next": "Next image",
                "admin": "Admin",
                "logout": "Logout",
                "analyze": "Analyze & caption",
                "publish": "Publish",
                "keep": "Keep",
                "remove": "Remove",
            },
            "panels": {
                "caption_title": "Caption",
                "admin_title": "Administration",
                "activity_title": "Activity",
            },
            "placeholders": {
                "image_empty": "No image loaded yet.",
            },
            "status": {
                "ready": "Ready.",
                "admin_mode_on": "Admin mode: on",
                "admin_mode_off": "Admin mode: off",
            },
        }
    )


class AIServiceLimits(BaseModel):
    """Client-side throttling defaults for the OpenAI calls."""

    rate_per_minute: int = Field(
        default=20,
        description="Default OpenAI rate limit in requests per minute",
    )


class InstagramLimits(BaseModel):
    """Bounds of the randomized human-like delay applied around Instagram actions."""

    delay_min_seconds: int = Field(default=1)
    delay_max_seconds: int = Field(default=3)


class WebLimits(BaseModel):
    """Tuning for the web layer, currently the image-listing cache TTL in seconds."""

    image_cache_ttl_seconds: float = Field(default=30.0)


class SMTPLimits(BaseModel):
    """SMTP tuning; ``timeout_seconds`` None leaves the library default in place."""

    timeout_seconds: float | None = None


class ServiceLimitsConfig(BaseModel):
    """Root of service_limits.yaml — operational tuning per outbound service."""

    ai: AIServiceLimits = AIServiceLimits()
    instagram: InstagramLimits = InstagramLimits()
    web: WebLimits = WebLimits()
    smtp: SMTPLimits = SMTPLimits()


class StaticConfig(BaseModel):
    """Aggregate of all static config files, one attribute per YAML file.

    Every section defaults to its built-in values, so an instance is always
    complete even when no YAML file was found.
    """

    ai_prompts: AIPromptsConfig = AIPromptsConfig()
    platform_limits: PlatformLimitsConfig = PlatformLimitsConfig()
    preview_text: PreviewTextConfig = PreviewTextConfig()
    web_ui_text: WebUITextConfig = WebUITextConfig()
    service_limits: ServiceLimitsConfig = ServiceLimitsConfig()


def _load_yaml(path: Path) -> dict[str, Any]:
    """Read one YAML file into a mapping, returning {} instead of raising.

    A missing file, a non-mapping document and a parse error are all logged as
    warnings and yield {}, so the caller falls back to defaults rather than
    failing to start.
    """
    if not path.exists():
        logger.warning("Static config file missing", extra={"path": str(path)})
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                logger.warning(
                    "Static config file did not contain a mapping; ignoring",
                    extra={"path": str(path)},
                )
                return {}
            return data
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "Failed to load static config file",
            extra={"path": str(path), "error": str(exc)},
        )
        return {}


def load_static_config(base_dir: str | None = None) -> StaticConfig:
    """Load static configuration from YAML files, falling back to safe defaults.

    Static config is non-secret and versioned in the repository. Callers should
    use get_static_config() rather than this function directly.
    """
    if base_dir is not None:
        root = Path(base_dir)
    else:
        env_dir = os.environ.get("PV2_STATIC_CONFIG_DIR")
        root = Path(env_dir) if env_dir else Path(__file__).with_name("static")

    ai_data = _load_yaml(root / "ai_prompts.yaml")
    platform_data = _load_yaml(root / "platform_limits.yaml")
    preview_data = _load_yaml(root / "preview_text.yaml")
    web_ui_data = _load_yaml(root / "web_ui_text.en.yaml")
    service_data = _load_yaml(root / "service_limits.yaml")

    return StaticConfig(
        ai_prompts=AIPromptsConfig(**ai_data) if ai_data else AIPromptsConfig(),
        platform_limits=PlatformLimitsConfig(**platform_data) if platform_data else PlatformLimitsConfig(),
        preview_text=PreviewTextConfig(**preview_data) if preview_data else PreviewTextConfig(),
        web_ui_text=WebUITextConfig(**web_ui_data) if web_ui_data else WebUITextConfig(),
        service_limits=ServiceLimitsConfig(**service_data) if service_data else ServiceLimitsConfig(),
    )


@lru_cache(maxsize=1)
def get_static_config() -> StaticConfig:
    """Cached accessor for static configuration.

    This is the primary entry point other modules should use.
    """
    return load_static_config(None)
