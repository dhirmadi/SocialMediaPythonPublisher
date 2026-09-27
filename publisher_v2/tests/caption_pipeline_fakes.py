"""Shared test fakes and builders — the single home for them (PUB-084).

Only external boundaries are faked: the OpenAI client (``FakeOpenAI``: a recording fake
that serves the vision and caption stages, or replays a script), storage (``BaseDummyStorage``
and ``SidecarStorage``), the Dropbox SDK client (``BaseDummyClient``) and publishers. Everything
in between — ``VisionAnalyzerOpenAI``, ``CaptionGeneratorOpenAI``, ``AIService``,
``WorkflowOrchestrator``, ``CaptionStore`` — is the real code. ``AIService`` is always built
with its real constructor (``stub_ai_service`` / ``real_ai_service``), never subclassed.

``make_app_config(**overrides)`` is the one ``ApplicationConfig`` builder for tests.

The conftest fixtures (``fake_openai`` and friends) are thin wrappers over this module.
Not a test module (no ``test_`` prefix), so pytest does not collect it.
"""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from publisher_v2.config.runtime_settings import RuntimeSettings
from publisher_v2.config.schema import (
    ApplicationConfig,
    DropboxConfig,
    OpenAIConfig,
)
from publisher_v2.core.models import CaptionSpec, ImageAnalysis, PublishResult
from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI, VisionAnalyzerOpenAI
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.services.storage_protocol import FileMetadata

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


class FakeCompletion:
    """A ``chat.completions.create`` result: one choice carrying ``content``, plus usage and id."""

    def __init__(self, content: str, *, usage: Any = None, id: str = "resp-test", model: str | None = None) -> None:
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=content))]
        self.usage = usage
        self.id = id
        self.model = model


def fake_usage(total: int = 100, prompt: int = 60, completion: int = 40) -> SimpleNamespace:
    """An OpenAI ``usage`` block for a ``FakeCompletion``."""
    return SimpleNamespace(total_tokens=total, prompt_tokens=prompt, completion_tokens=completion)


# A script entry: text, a JSON-able dict/list, a ready FakeCompletion, an exception (instance or
# class) to raise, or a callable taking the create() kwargs and returning/raising any of those.
ScriptItem = Any


class FakeOpenAI:
    """Stands in for ``AsyncOpenAI``; records every ``chat.completions.create`` call.

    Two modes:

    - **Scripted** (``script=[...]``): each call consumes the next entry, in order, whatever
      the stage. Strings are the reply text, dicts/lists are JSON-encoded, a ``FakeCompletion``
      is returned as is, an exception is raised, a callable is called with the create() kwargs.
      Once the script is exhausted the last entry repeats.
    - **Pipeline** (no script): vision calls (the ones carrying an ``image_url`` part, or the
      owner-persona call) get ``vision_payload``; caption calls get a JSON object keyed by
      ``platforms`` (platform keys only — never ``sd_caption``).
    """

    def __init__(
        self,
        platforms: list[str] | None = None,
        *,
        script: list[ScriptItem] | None = None,
        vision_payload: Callable[[int, dict[str, Any]], str] = default_vision_payload,
        caption_text: Callable[[int, str], str] = default_caption_text,
    ) -> None:
        if script is not None and not script:
            raise ValueError("FakeOpenAI script must hold at least one entry")
        self.platforms = list(platforms or [])
        self.script = list(script) if script is not None else None
        self.calls: list[dict[str, Any]] = []
        self.client_kwargs: list[dict[str, Any]] = []  # one entry per AsyncOpenAI(...) construction
        self.closed = 0
        self._vision_payload = vision_payload
        self._caption_text = caption_text
        self.chat = SimpleNamespace(completions=self)

    @property
    def vision_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if is_vision_call(c)]

    @property
    def caption_calls(self) -> list[dict[str, Any]]:
        return [c for c in self.calls if not is_vision_call(c)]

    async def create(self, **kwargs: Any) -> FakeCompletion:
        self.calls.append(kwargs)
        if self.script is not None:
            return self._play(self.script[min(len(self.calls), len(self.script)) - 1], kwargs)
        if is_vision_call(kwargs):
            return FakeCompletion(self._vision_payload(len(self.vision_calls), kwargs))
        n = len(self.caption_calls)
        return FakeCompletion(json.dumps({p: self._caption_text(n, p) for p in self.platforms}))

    def _play(self, item: ScriptItem, kwargs: dict[str, Any]) -> FakeCompletion:
        if isinstance(item, BaseException) or (isinstance(item, type) and issubclass(item, BaseException)):
            raise item
        if callable(item) and not isinstance(item, FakeCompletion):
            return self._play(item(kwargs), kwargs)
        if isinstance(item, FakeCompletion):
            return item
        if isinstance(item, dict | list):
            return FakeCompletion(json.dumps(item))
        return FakeCompletion(str(item))

    async def close(self) -> None:
        self.closed += 1


def install_fake_openai(monkeypatch: pytest.MonkeyPatch, fake: FakeOpenAI) -> FakeOpenAI:
    """Make every ``AsyncOpenAI(...)`` the production code builds return ``fake``.

    The constructor kwargs are recorded on ``fake.client_kwargs``. Prefer the ``fake_openai``
    fixture, which builds and installs in one step.
    """

    def _construct(*_args: Any, **kwargs: Any) -> FakeOpenAI:
        fake.client_kwargs.append(kwargs)
        return fake

    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", _construct)
    return fake


def openai_config(**overrides: Any) -> OpenAIConfig:
    kwargs: dict[str, Any] = {"api_key": "sk-test", "vision_max_dimension": 0, "vision_fallback_enabled": False}
    kwargs.update(overrides)
    return OpenAIConfig(**kwargs)


def real_ai_service(cfg: OpenAIConfig | None = None) -> AIService:
    """The real AIService; a generous rate budget so a regeneration does not wait 3s for a slot."""
    cfg = cfg or openai_config()
    return AIService(
        VisionAnalyzerOpenAI(cfg), CaptionGeneratorOpenAI(cfg), settings=RuntimeSettings(ai_rate_per_minute=6000)
    )


def pipeline_config(
    *, telegram: bool = False, instagram: bool = False, email: bool = False, openai: OpenAIConfig | None = None
) -> ApplicationConfig:
    return make_app_config(
        openai=openai or openai_config(),
        platforms={"telegram_enabled": telegram, "instagram_enabled": instagram, "email_enabled": email},
        captionfile={"extended_metadata_enabled": True},
    )


# --- application config -----------------------------------------------------------

# Valid defaults for every required ApplicationConfig section. Dropbox storage by default;
# pass ``managed=`` to switch provider (the Dropbox default is then dropped).
_APP_CONFIG_DEFAULTS: dict[str, dict[str, Any]] = {
    "dropbox": {
        "app_key": "k",
        "app_secret": "s",
        "refresh_token": "r",
        "image_folder": "/Photos",
        "archive_folder": "archive",
    },
    "storage_paths": {"image_folder": "/Photos"},
    "openai": {"api_key": "sk-test"},  # pragma: allowlist secret
    "platforms": {},
    "content": {"hashtag_string": "", "archive": False, "debug": False},
}


def make_app_config(**overrides: Any) -> ApplicationConfig:
    """The one test builder for ``ApplicationConfig``: valid defaults plus ``overrides``.

    A model instance (or ``None``) replaces that section; a dict is merged onto the section's
    defaults (or, for a section without defaults, validated as the section). The result goes
    through the real model validation.
    """
    fields: dict[str, Any] = {name: dict(values) for name, values in _APP_CONFIG_DEFAULTS.items()}
    if "managed" in overrides and "dropbox" not in overrides:
        fields.pop("dropbox")
    for name, value in overrides.items():
        if isinstance(value, dict) and isinstance(fields.get(name), dict):
            fields[name] = {**fields[name], **value}
        else:
            fields[name] = value
    return ApplicationConfig(**fields)


# --- storage, AI stage and publisher dummies -------------------------------------


class BaseDummyStorage:
    """
    Base dummy storage class that can be customized per test.

    This centralizes the common storage mock pattern found across 8+ test files.
    Subclasses or instances can override specific methods as needed.
    """

    def __init__(
        self,
        config: DropboxConfig | None = None,
        images: list[str] | None = None,
        content: bytes = b"\x89PNG\r\n\x1a\n",
    ) -> None:
        self.config = config or DropboxConfig(
            app_key="k",
            app_secret="s",
            refresh_token="r",
            image_folder="/Photos",
            archive_folder="archive",
        )
        self._images = images or ["test.jpg"]
        self._content = content
        # Track operations for assertions
        self.sidecar_text: str | None = None
        self.sidecars_written: int = 0
        self.archives: int = 0
        self.moves: list[tuple[str, str, str]] = []  # (folder, filename, target)

    async def list_images(self, folder: str) -> list[str]:
        return self._images

    async def download_image(self, folder: str, filename: str) -> bytes:
        return self._content

    async def get_temporary_link(self, folder: str, filename: str) -> str:
        return f"https://example.com/tmp/{filename}"

    async def get_file_metadata(self, folder: str, filename: str) -> FileMetadata:
        return FileMetadata(file_id="id:XYZ", revision="123", modified_at=None, size=None)

    async def write_sidecar_text(self, folder: str, filename: str, text: str) -> None:
        self.sidecar_text = text
        self.sidecars_written += 1

    async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None:
        return None  # Default: no sidecar

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        self.archives += 1

    async def move_image_with_sidecars(self, folder: str, filename: str, target: str) -> None:
        self.moves.append((folder, filename, target))

    async def delete_file_with_sidecar(self, folder: str, filename: str) -> None:
        pass

    async def ensure_folder_exists(self, folder_path: str) -> None:
        pass

    async def list_images_with_hashes(self, folder: str) -> list[tuple[str, str]]:
        return [(name, "") for name in self._images]

    async def get_thumbnail(
        self,
        folder: str,
        filename: str,
        size: object = None,
        format: object = None,
    ) -> bytes:
        return b"\xff\xd8\xff\xe0"  # minimal JPEG header

    def supports_content_hashing(self) -> bool:
        return False


class BaseDummyAnalyzer:
    """
    Base dummy vision analyzer for workflow tests.

    Centralizes the DummyAnalyzer pattern found across 7+ test files.
    """

    def __init__(
        self,
        analysis: ImageAnalysis | None = None,
        extended_fields: bool = False,
    ) -> None:
        if analysis:
            self._analysis = analysis
        elif extended_fields:
            self._analysis = ImageAnalysis(
                description="Fine-art portrait, soft light.",
                mood="calm",
                tags=["portrait", "softlight"],
                nsfw=False,
                safety_labels=[],
                subject="single subject, torso",
                style="fine-art",
                lighting="soft directional",
                camera="50mm",
                clothing_or_accessories="rope harness",
                aesthetic_terms=["minimalist", "graphic"],
                pose="upright",
                composition="center-weighted",
                background="plain backdrop",
                color_palette="black and white",
            )
        else:
            self._analysis = ImageAnalysis(
                description="Test image description",
                mood="neutral",
                tags=["test", "fixture"],
                nsfw=False,
                safety_labels=[],
            )

    async def analyze(self, url_or_bytes: str | bytes) -> tuple[ImageAnalysis, None]:
        return self._analysis, None


class BaseDummyGenerator:
    """
    Base dummy caption generator for workflow tests.

    Centralizes the DummyGenerator pattern found across 7+ test files.
    """

    def __init__(
        self,
        caption: str = "test caption #tags",
        sd_caption: str | None = "fine-art portrait, soft light, calm mood",
        config: OpenAIConfig | None = None,
    ) -> None:
        self._caption = caption
        self._sd_caption = sd_caption
        self.sd_caption_model = "gpt-4o-mini"
        # sd_caption=None: AIService skips generate_with_sd and uses generate() alone.
        self.sd_caption_enabled = sd_caption is not None
        if config:
            self.model = config.caption_model

    async def generate(self, analysis: ImageAnalysis, spec: CaptionSpec) -> tuple[str, None]:
        return self._caption, None

    async def generate_with_sd(self, analysis: ImageAnalysis, spec: CaptionSpec) -> tuple[dict[str, str], None]:
        return {"caption": self._caption, "sd_caption": self._sd_caption}, None


class MultiCaptionDummyGenerator(BaseDummyGenerator):
    """A ``BaseDummyGenerator`` that also answers the multi-platform path: one caption per spec."""

    async def generate_multi(
        self, analysis: ImageAnalysis, specs: dict[str, CaptionSpec], **kwargs: object
    ) -> tuple[dict[str, str], None]:
        return {platform: self._caption for platform in specs}, None


# No real pacing in tests: the limiter's minimum interval rounds to zero.
UNTHROTTLED = RuntimeSettings(ai_rate_per_minute=60_000_000)


def stub_ai_service(analyzer: Any = None, generator: Any = None) -> AIService:
    """The real ``AIService`` over stub stages, with no rate pacing.

    Defaults: ``BaseDummyAnalyzer()`` and a ``BaseDummyGenerator`` that answers ``generate()`` with
    ``"hello world"`` (no SD caption, no multi-platform path). Never subclass ``AIService`` to skip
    its constructor; pass the stage fakes in here.
    """
    return AIService(
        analyzer if analyzer is not None else BaseDummyAnalyzer(),
        generator if generator is not None else BaseDummyGenerator(caption="hello world", sd_caption=None),
        settings=UNTHROTTLED,
    )


class BaseDummyPublisher:
    """
    Base dummy publisher for workflow tests.

    Centralizes the DummyPublisher pattern found across 5+ test files.
    """

    def __init__(
        self,
        platform: str = "dummy",
        enabled: bool = True,
        success: bool = True,
        error: str | None = None,
    ) -> None:
        self._platform = platform
        self._enabled = enabled
        self._success = success
        self._error = error
        self.publish_calls: list[tuple[str, str]] = []  # Track (image_path, caption)

    @property
    def platform_name(self) -> str:
        return self._platform

    def is_enabled(self) -> bool:
        return self._enabled

    async def publish(self, image_path: str, caption: str, context: dict[str, Any] | None = None) -> PublishResult:
        self.publish_calls.append((image_path, caption))
        return PublishResult(
            success=self._success,
            platform=self._platform,
            error=self._error,
        )


# --- Dropbox SDK client dummy ----------------------------------------------------


class BaseDummyClient:
    """
    Base dummy Dropbox client for low-level storage tests.

    Centralizes the DummyClient pattern found across 4+ test files.
    """

    def __init__(self, sidecar_exists: bool = True) -> None:
        self.created_dirs: list[str] = []
        self.moves: list[tuple[str, str]] = []
        self.uploads: list[tuple[str, bytes, Any]] = []
        self.sidecar_bytes: bytes | None = b"sidecar-content"
        self.sidecar_exists: bool = sidecar_exists

    def files_create_folder_v2(self, path: str) -> None:
        self.created_dirs.append(path)

    def files_move_v2(self, from_path: str, to_path: str, autorename: bool = False) -> None:
        from dropbox.exceptions import ApiError

        # Simulate sidecar missing by raising ApiError when appropriate.
        if from_path.endswith(".txt") and not self.sidecar_exists:

            class _Error:
                def is_path(self) -> bool:
                    return True

                def get_path(self) -> SimpleNamespace:
                    return SimpleNamespace(is_not_found=lambda: True)

            raise ApiError("req", _Error(), "not_found", "en-US")
        self.moves.append((from_path, to_path))

    def files_upload(
        self,
        data: bytes,
        path: str,
        mode: Any,
        mute: bool = False,
        strict_conflict: bool = False,
    ) -> None:
        self.uploads.append((path, data, mode))

    def files_download(self, path: str) -> tuple[None, SimpleNamespace]:
        from dropbox.exceptions import ApiError

        if not self.sidecar_exists:

            class _PathError:
                def is_not_found(self) -> bool:
                    return True

            class _Error:
                def is_path(self) -> bool:
                    return True

                def get_path(self) -> _PathError:
                    return _PathError()

            raise ApiError("request-id", _Error(), "not_found", "en-US")
        content = self.sidecar_bytes or b"sidecar-bytes"
        return None, SimpleNamespace(content=content)


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
