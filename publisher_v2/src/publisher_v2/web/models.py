"""Pydantic request/response models for the web admin JSON API.

These shapes are the wire contract consumed by the single-page admin UI, so
fields are additive-only: new optional fields are fine, renames and removals
break deployed browsers. Nothing here may carry secret material.
"""

from typing import Any

from pydantic import BaseModel


class ImageListResponse(BaseModel):
    """Filenames of the images currently available for curation, plus their count."""

    filenames: list[str]
    count: int


class ImageResponse(BaseModel):
    """One image and everything the UI needs to render it without a second call.

    ``temp_url`` is a short-lived storage link, not a permanent address.
    ``has_sidecar`` says whether analysis metadata already exists; when it does,
    ``caption``/``sd_caption``/``caption_generated`` are populated from the
    sidecar so the grid can show captions without re-running the AI.
    """

    filename: str
    temp_url: str
    thumbnail_url: str | None = None
    sha256: str | None = None
    caption: str | None = None
    sd_caption: str | None = None
    metadata: dict[str, Any] | None = None
    has_sidecar: bool
    # #147: generated per-platform captions from the sidecar, shown without re-analyzing.
    caption_generated: dict[str, str] | None = None
    # #147: caption length limit per enabled platform, so the editors can count before Analyze.
    platform_limits: dict[str, int] | None = None


class AnalysisResponse(BaseModel):
    """Result of analyzing one image and generating its captions.

    ``platform_captions`` holds the per-platform text the publish call expects;
    ``sidecar_written`` reports whether the analysis was persisted alongside the
    image, and ``cached`` whether it was served from an existing sidecar instead
    of a fresh AI run.
    """

    filename: str
    description: str
    mood: str
    tags: list[str]
    nsfw: bool
    caption: str
    sd_caption: str | None = None
    alt_text: str | None = None
    sidecar_written: bool = False
    platform_captions: dict[str, str] | None = None
    # #147: caption length limit per enabled platform, for the per-platform editors.
    platform_limits: dict[str, int] | None = None
    # #80: True when the caption was served from the sidecar cache rather than
    # a fresh AI run. Default False keeps the response backward compatible.
    cached: bool = False


class PublishRequest(BaseModel):
    """Body of a publish request: which platforms, and with what caption text.

    ``platforms`` defaults to every enabled platform when omitted. Prefer
    ``captions``, which must cover exactly the targeted platforms; the single
    ``caption`` field is the legacy form applied to all of them.
    """

    platforms: list[str] | None = None
    # Legacy: one caption for every platform.
    caption: str | None = None
    # #147: per-platform captions (platform name -> text); wins over ``caption``.
    captions: dict[str, str] | None = None


class PublishResponse(BaseModel):
    """Outcome of a publish attempt, per platform.

    ``results`` maps platform name to that platform's raw result payload.
    ``any_success`` is true when at least one platform accepted the post, and
    ``archived`` whether the image was moved out of the source folder afterwards.
    """

    filename: str
    results: dict[str, dict[str, Any]]
    archived: bool
    any_success: bool


class ErrorResponse(BaseModel):
    """Error body returned for non-2xx API responses; ``detail`` is optional context."""

    error: str
    detail: str | None = None


class AdminStatusResponse(BaseModel):
    """Whether the current session is authenticated as admin.

    ``admin`` is false both for anonymous callers and for machine clients using
    header auth only, since header auth never grants admin. ``error`` carries a
    non-fatal reason (for example admin login being unconfigured).
    """

    admin: bool
    error: str | None = None


class CurationResponse(BaseModel):
    """Result of a curation action on one image.

    ``action`` is ``"keep"``, ``"remove"`` or ``"delete"``.
    ``destination_folder`` is the folder the image was moved into, and is empty
    for ``"delete"``, which has no destination. ``preview_only`` is true when
    the action was reported but deliberately not carried out.
    """

    filename: str
    action: str  # "keep" or "remove"
    destination_folder: str
    preview_only: bool = False


class VoiceProfileResponse(BaseModel):
    """PUB-029: response shape for GET /api/config/voice-profile."""

    voice_profile: list[str] | None = None
    enabled: bool = False
    # PUB-050 AC5: this setter is process-local; there is no orchestrator
    # write-back path, so the response says so and names the durable field.
    persisted: bool = False
    orchestrator_field: str = "content.voice_profile"


class VoiceProfileUpdateRequest(BaseModel):
    """PUB-029: request body for POST /api/config/voice-profile."""

    voice_profile: list[str]
