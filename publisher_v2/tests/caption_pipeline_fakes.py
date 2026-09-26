"""Shared fakes for the PUB-051 caption-pipeline tests.

Only external boundaries are faked: the OpenAI client (one recording fake that
serves both the vision stage and the caption stage), storage (a
``BaseDummyStorage`` whose sidecar round-trips), and publishers. Everything in
between — ``VisionAnalyzerOpenAI``, ``CaptionGeneratorOpenAI``, ``AIService``,
``WorkflowOrchestrator``, ``CaptionStore`` — is the real code.

Not a test module (no ``test_`` prefix), so pytest does not collect it.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest
from conftest import BaseDummyStorage

from publisher_v2.config.schema import (
    ApplicationConfig,
    CaptionFileConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
)
from publisher_v2.core.models import PublishResult
from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI, VisionAnalyzerOpenAI
from publisher_v2.services.publishers.base import Publisher

# --- canned vision output -----------------------------------------------------

# The neutral/analyst metadata a vision call returns. Deliberately carries hex
# colours and snake_case tags, the shapes AC3 says must never reach the caption prompt.
VISION_NEUTRAL: dict[str, Any] = {
    "description": "A woman kneels on a bare wooden floor, hemp rope crossing her shoulders",
    "mood": "patient",
    "tags": ["rope_art", "negative_space", "jute_harness", "window_light", "kneeling_pose"],
    "nsfw": True,
    "safety_labels": ["adult_nudity_non_explicit"],
    "subject": "kneeling figure in rope",
    "style": "studio shibari, fine-art figure study",
    "lighting": "hard window light from camera left",
    "camera": "eye level, normal focal length, shallow depth of field",
    "clothing_or_accessories": "natural jute rope harness",
    "aesthetic_terms": ["chiaroscuro", "tenebrism", "minimalism"],
    "pose": "kneeling, head slightly bowed",
    "composition": "centered figure, generous negative space above",
    "background": "bare plaster wall and wooden floorboards",
    "color_palette": "#1a1a1a, #c8a27a, #f2efe9",
    "alt_text": "A kneeling person with rope across the shoulders on a wooden floor.",
    "distinctive_detail": "a frayed rope end left deliberately untrimmed",
}

# Caption-facing fields. The fake only returns them from a call whose system
# message carries the owner-persona marker (AC5), so their presence in an
# ImageAnalysis proves that call ran.
SENSORY_DETAIL = ["cool jute pressed against a warm wrist", "breath held under the second wrap"]
MOOD_NOTE = "The quiet before the last knot settles is the part worth keeping."

SD_FROM_CALL = "SD_FROM_VISION_CALL_{n}"

OWNER_MARKER_LITERAL = "OWNER-VOICE SECTION:"


# --- OpenAI message helpers ---------------------------------------------------


def _messages(kwargs: dict[str, Any]) -> list[dict[str, Any]]:
    return [dict(m) for m in kwargs.get("messages", [])]


def system_text(kwargs: dict[str, Any]) -> str:
    """All system-message text of one recorded ``chat.completions.create`` call."""
    return "\n".join(str(m.get("content", "")) for m in _messages(kwargs) if m.get("role") == "system")


def user_text(kwargs: dict[str, Any]) -> str:
    """All user-message text (string content or text parts; image parts skipped)."""
    parts: list[str] = []
    for m in _messages(kwargs):
        if m.get("role") != "user":
            continue
        content = m.get("content")
        if isinstance(content, str):
            parts.append(content)
        elif isinstance(content, list):
            for part in content:
                part = dict(part)
                if part.get("type") == "text":
                    parts.append(str(part.get("text", "")))
    return "\n".join(parts)


def image_part(kwargs: dict[str, Any]) -> dict[str, Any] | None:
    """The ``image_url`` payload (``{"url", "detail"}``) of a call, or None."""
    for m in _messages(kwargs):
        content = m.get("content")
        if isinstance(content, list):
            for part in content:
                part = dict(part)
                if part.get("type") == "image_url":
                    return dict(part.get("image_url") or {})
    return None


def is_vision_call(kwargs: dict[str, Any]) -> bool:
    """A vision-stage call: it carries the image, or it is the owner-persona call (which may be text-only)."""
    return image_part(kwargs) is not None or OWNER_MARKER_LITERAL in system_text(kwargs)


def default_vision_payload(call_number: int, kwargs: dict[str, Any]) -> str:
    """Neutral metadata + a per-call sd_caption; caption-facing fields only under the marker."""
    payload: dict[str, Any] = dict(VISION_NEUTRAL)
    payload["sd_caption"] = SD_FROM_CALL.format(n=call_number)
    if OWNER_MARKER_LITERAL in system_text(kwargs):
        payload["sensory_detail"] = list(SENSORY_DETAIL)
        payload["mood_note"] = MOOD_NOTE
    return json.dumps(payload)


def default_caption_text(call_number: int, platform: str) -> str:
    """Short, history-disjoint captions so neither the condense pass nor the similarity gate fires."""
    words = ["amber", "cobalt", "saffron", "umber", "viridian", "ochre", "cerulean", "carmine", "sepia"]
    return f"{words[call_number % len(words)]} {platform} morning, kettle ticking, draft number {call_number}."


class _Resp:
    def __init__(self, content: str) -> None:
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=content))]
        self.usage = None
        self.id = "resp-test"


class FakeOpenAI:
    """Records every ``chat.completions.create`` call; answers vision and caption calls.

    Vision calls are the ones carrying an ``image_url`` part. Caption calls get a
    JSON object keyed by ``platforms`` (platform keys only — never ``sd_caption``).
    """

    def __init__(
        self,
        platforms: list[str],
        *,
        vision_payload: Callable[[int, dict[str, Any]], str] = default_vision_payload,
        caption_text: Callable[[int, str], str] = default_caption_text,
    ) -> None:
        self.platforms = list(platforms)
        self.calls: list[dict[str, Any]] = []
        self._vision_payload = vision_payload
        self._caption_text = caption_text
        self.chat = SimpleNamespace(completions=self)

    @property
    def vision_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if is_vision_call(c)]

    @property
    def caption_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if not is_vision_call(c)]

    async def create(self, **kwargs: Any) -> _Resp:
        self.calls.append(kwargs)
        if is_vision_call(kwargs):
            return _Resp(self._vision_payload(len(self.vision_calls), kwargs))
        n = len(self.caption_calls)
        return _Resp(json.dumps({p: self._caption_text(n, p) for p in self.platforms}))

    async def close(self) -> None:
        return None


def install_fake_openai(monkeypatch: pytest.MonkeyPatch, fake: FakeOpenAI) -> None:
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda *_a, **_kw: fake)


def openai_config(**overrides: Any) -> OpenAIConfig:
    kwargs: dict[str, Any] = {"api_key": "sk-test", "vision_max_dimension": 0, "vision_fallback_enabled": False}
    kwargs.update(overrides)
    return OpenAIConfig(**kwargs)


def real_ai_service(cfg: OpenAIConfig | None = None) -> AIService:
    """The real AIService; a generous rate budget so a regeneration does not wait 3s for a slot."""
    from publisher_v2.config.runtime_settings import RuntimeSettings

    cfg = cfg or openai_config()
    return AIService(
        VisionAnalyzerOpenAI(cfg), CaptionGeneratorOpenAI(cfg), settings=RuntimeSettings(ai_rate_per_minute=6000)
    )


def pipeline_config(
    *, telegram: bool = False, instagram: bool = False, email: bool = False, openai: OpenAIConfig | None = None
) -> ApplicationConfig:
    return ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        ),
        storage_paths=StoragePathConfig(image_folder="/Photos"),
        openai=openai or openai_config(),
        platforms=PlatformsConfig(telegram_enabled=telegram, instagram_enabled=instagram, email_enabled=email),
        content=ContentConfig(hashtag_string="", archive=False, debug=False),
        captionfile=CaptionFileConfig(extended_metadata_enabled=True),
    )


# --- storage and publishers -----------------------------------------------------


class SidecarStorage(BaseDummyStorage):
    """Per-filename image bytes and a sidecar that reads back what was written."""

    def __init__(self, images: list[str]) -> None:
        super().__init__(images=images)
        self.sidecars: dict[str, str] = {}

    async def download_image(self, folder: str, filename: str) -> bytes:
        return f"image-bytes:{filename}".encode()

    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        await super().write_sidecar_text(folder, filename, text)
        self.sidecars[filename] = text

    async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None:
        text = self.sidecars.get(filename)
        return text.encode() if text is not None else None


class ScriptedPublisher(Publisher):
    """Succeeds or fails per a script; records the caption it was handed each call."""

    def __init__(self, name: str, outcomes: list[bool]) -> None:
        self._name = name
        self._outcomes = outcomes
        self.captions: list[str] = []

    @property
    def platform_name(self) -> str:
        return self._name

    def is_enabled(self) -> bool:
        return True

    async def publish(self, image_path: str, caption: str, context: dict | None = None) -> PublishResult:
        n = len(self.captions)
        self.captions.append(caption)
        if self._outcomes[min(n, len(self._outcomes) - 1)]:
            return PublishResult(success=True, platform=self._name, post_id=f"{self._name}-{n}")
        return PublishResult(success=False, platform=self._name, error="scripted failure")


def jpeg_bytes(width: int, height: int, color: tuple[int, int, int]) -> bytes:
    """A real, decodable JPEG (vision resizes byte input locally)."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="JPEG")
    return buf.getvalue()
