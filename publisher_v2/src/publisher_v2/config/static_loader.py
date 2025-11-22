from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from pydantic import BaseModel, Field

logger = logging.getLogger("publisher_v2.config.static")


class AIVisionPrompts(BaseModel):
    system: Optional[str] = Field(
        default=None,
        description="System prompt for vision analysis",
    )
    user: Optional[str] = Field(
        default=None,
        description="User instructions for vision analysis",
    )


class AICaptionPrompts(BaseModel):
    system: Optional[str] = Field(
        default=None,
        description="System prompt for caption generation",
    )
    role: Optional[str] = Field(
        default=None,
        description="Role/user prompt template for caption generation",
    )


class AISDCaptionPrompts(BaseModel):
    system: Optional[str] = Field(
        default=None,
        description="System prompt for SD caption generation",
    )
    role: Optional[str] = Field(
        default=None,
        description="Role/user prompt template for SD caption generation",
    )


class AIPromptsConfig(BaseModel):
    vision: AIVisionPrompts = AIVisionPrompts()
    caption: AICaptionPrompts = AICaptionPrompts()
    sd_caption: AISDCaptionPrompts = AISDCaptionPrompts()


class PlatformLimit(BaseModel):
    max_caption_length: Optional[int] = Field(
        default=None,
        description="Maximum caption length for this platform",
    )
    max_hashtags: Optional[int] = Field(
        default=None,
        description="Maximum number of hashtags for this platform",
    )
    resize_width_px: Optional[int] = Field(
        default=None,
        description="Maximum resize width in pixels for this platform",
    )


class PlatformLimitsConfig(BaseModel):
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
    )
    generic: PlatformLimit = PlatformLimit(
        max_caption_length=2200,
    )


class PreviewTextConfig(BaseModel):
    headers: Dict[str, str] = Field(
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
    messages: Dict[str, str] = Field(
        default_factory=lambda: {
            "no_caption_yet": "No caption yet.",
            "analysis_skipped": "⚠ Analysis skipped (FEATURE_ANALYZE_CAPTION=false)",
            "publish_disabled": "⚠ Publish feature disabled (FEATURE_PUBLISH=false). No platforms will be contacted.",
        }
    )


class WebUITextConfig(BaseModel):
    values: Dict[str, Any] = Field(
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
            "admin_dialog": {
                "title": "Admin login",
                "description": "Enter the admin password to enable analysis and publishing.",
                "password_placeholder": "Admin password",
            },
        }
    )


class AIServiceLimits(BaseModel):
    rate_per_minute: int = Field(
        default=20,
        description="Default OpenAI rate limit in requests per minute",
    )


class InstagramLimits(BaseModel):
    delay_min_seconds: int = Field(default=1)
    delay_max_seconds: int = Field(default=3)


class WebLimits(BaseModel):
    image_cache_ttl_seconds: float = Field(default=30.0)


class SMTPLimits(BaseModel):
    timeout_seconds: Optional[float] = None


class ServiceLimitsConfig(BaseModel):
    ai: AIServiceLimits = AIServiceLimits()
    instagram: InstagramLimits = InstagramLimits()
    web: WebLimits = WebLimits()
    smtp: SMTPLimits = SMTPLimits()


class StaticConfig(BaseModel):
    ai_prompts: AIPromptsConfig = AIPromptsConfig()
    platform_limits: PlatformLimitsConfig = PlatformLimitsConfig()
    preview_text: PreviewTextConfig = PreviewTextConfig()
    web_ui_text: WebUITextConfig = WebUITextConfig()
    service_limits: ServiceLimitsConfig = ServiceLimitsConfig()


def _load_yaml(path: Path) -> Dict[str, Any]:
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
    """
    Load static configuration from YAML files, falling back to safe defaults.

    Static config is non-secret and versioned in the repository. Callers should
    use get_static_config() rather than this function directly.
    """
    if base_dir is not None:
        root = Path(base_dir)
    else:
        env_dir = os.environ.get("PV2_STATIC_CONFIG_DIR")
        if env_dir:
            root = Path(env_dir)
        else:
            root = Path(__file__).with_name("static")

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
    """
    Cached accessor for static configuration.

    This is the primary entry point other modules should use.
    """
    return load_static_config(None)



