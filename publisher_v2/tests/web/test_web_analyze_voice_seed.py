"""PUB-050: how the web analyze path seeds the per-image voice sample.

``WebImageService.analyze_and_caption`` picks the sampler's seed at
``web/service.py``'s caption step: ``sha256(analysis_source)`` when the vision
call already holds the image bytes (``vision_max_dimension > 0``, the modern
default), and the ``filename`` on the legacy presigned-URL path
(``vision_max_dimension == 0``) that never downloads the image.

Line coverage cannot tell those two branches apart — a regression that always
seeded on ``filename`` would execute the same lines and look fine, while every
re-upload of the same name silently reused one image's examples. So both
branches are pinned by observable effect, as a matched pair that no single
implementation can satisfy at once:

- bytes branch: same name, different bytes -> DIFFERENT sample;
- URL branch: same name, different bytes -> SAME sample (the bytes are never
  fetched there, so nothing about them can reach the seed).

The file also pins that the seed is not computed at all when voice matching is
off, since it would be thrown away.

Stubs sit at the same seams as the neighbouring web-service tests
(``test_web_analyze_storage_ops_meter``): the Dropbox client and the AI calls.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from publisher_v2.core.models import ImageAnalysis
from publisher_v2.services.ai import sample_voice_examples

FILENAME = "img.jpg"
PROFILE: list[str] = [f"Owner line number {i}." for i in range(1, 13)]
# Two different images uploaded under the SAME name. Verified to produce
# different samples for this profile, so a filename seed cannot fake this.
IMAGE_A = b"image-bytes-A"
IMAGE_B = b"image-bytes-B"


def _make_service(
    monkeypatch: pytest.MonkeyPatch,
    *,
    profile: list[str] | None = PROFILE,
    vision_max_dimension: int | None = None,
) -> Any:
    """A real WebImageService with stubbed storage and AI.

    ``profile`` defaults to the corpus above (voice matching on). Pass ``None``
    for the default tenant: no profile, so voice matching stays off.
    ``vision_max_dimension=0`` selects the legacy presigned-URL vision path,
    which never downloads the image.
    """
    openai_settings: dict[str, Any] = {}
    if vision_max_dimension is not None:
        openai_settings["vision_max_dimension"] = vision_max_dimension

    monkeypatch.setenv("STORAGE_PATHS", '{"root": "/Photos", "archive": "archive"}')
    monkeypatch.setenv("PUBLISHERS", json.dumps([{"type": "telegram", "channel_id": "@chan"}]))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tg")
    monkeypatch.setenv("OPENAI_SETTINGS", json.dumps(openai_settings))
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
    monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
    monkeypatch.setenv("CONTENT_SETTINGS", json.dumps({"voice_profile": profile} if profile else {}))
    monkeypatch.delenv("ORCHESTRATOR_BASE_URL", raising=False)

    with patch("publisher_v2.services.storage.dropbox.Dropbox"):
        from publisher_v2.web.service import WebImageService

        service = WebImageService()

    assert service.config.features.voice_matching_enabled is bool(profile), (
        "voice matching must follow the presence of a profile"
    )
    expected_dimension = 1024 if vision_max_dimension is None else vision_max_dimension
    assert service.config.openai.vision_max_dimension == expected_dimension, "the vision branch was not selected"

    service.storage.get_temporary_link = AsyncMock(return_value="http://temp")  # type: ignore[method-assign]
    service.storage.list_images = AsyncMock(return_value=[FILENAME])  # type: ignore[method-assign]
    service.storage.download_sidecar_if_exists = AsyncMock(return_value=None)  # type: ignore[method-assign]

    analysis = ImageAnalysis(description="Test", mood="neutral", tags=["t"], nsfw=False, safety_labels=[])
    service.ai_service.analyzer.analyze = AsyncMock(return_value=(analysis, None))  # type: ignore[method-assign, union-attr]
    # PUB-051 AC4/AC5: a 4-tuple (captions, None, usages, angles); the SD prompt comes from vision, not here.
    service.ai_service.create_multi_caption_pair_from_analysis = AsyncMock(  # type: ignore[method-assign, union-attr]
        return_value=({"telegram": "fresh AI caption"}, None, [], {"telegram": "moment"})
    )
    # No real OpenAI call if the multi path ever fails: the caption-only fallback would
    # otherwise reach api.openai.com with the test key.
    service.ai_service.create_caption_from_analysis = AsyncMock(  # type: ignore[method-assign, union-attr]
        side_effect=AssertionError("caption-only fallback ran; the multi-caption path failed")
    )
    return service


async def _voice_examples_for(service: Any, image_bytes: bytes) -> list[str] | None:
    """Analyze ``FILENAME`` with ``image_bytes`` behind it; return the sample the AI call got."""
    service.storage.download_image = AsyncMock(return_value=image_bytes)
    service.ai_service.create_multi_caption_pair_from_analysis.reset_mock()

    with patch("publisher_v2.services.sidecar.generate_and_upload_sidecar", new=AsyncMock(return_value=1.0)):
        await service.analyze_and_caption(FILENAME)

    call = service.ai_service.create_multi_caption_pair_from_analysis.await_args
    assert call is not None, "the caption call never happened"
    return call.kwargs["voice_examples"]


async def test_analyze_seeds_voice_examples_on_the_image_bytes_not_the_filename(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two different images under one filename must not share a voice sample."""
    service = _make_service(monkeypatch)

    first = await _voice_examples_for(service, IMAGE_A)
    second = await _voice_examples_for(service, IMAGE_B)

    assert first, "voice matching is on, so the caption call must carry examples"
    assert first != second, (
        "the same filename produced the same sample for two different images — "
        "the seed came from the filename, not the image bytes"
    )
    # Pin the seed exactly, so the branch cannot drift to some other bytes-derived value.
    assert first == sample_voice_examples(
        PROFILE, seed_source=hashlib.sha256(IMAGE_A).hexdigest(), platform_tags=None, platforms=["telegram"]
    )
    assert second == sample_voice_examples(
        PROFILE, seed_source=hashlib.sha256(IMAGE_B).hexdigest(), platform_tags=None, platforms=["telegram"]
    )


async def test_analyze_gives_the_same_image_the_same_voice_examples_every_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the contract: stable per image, so a re-analyze is not a re-roll."""
    service = _make_service(monkeypatch)

    first = await _voice_examples_for(service, IMAGE_A)
    again = await _voice_examples_for(service, IMAGE_A)

    assert first == again, "re-analyzing the same image re-rolled its voice examples"


@contextlib.contextmanager
def _sha256_calls_over(payload: bytes) -> Iterator[list[bytes]]:
    """Record every ``hashlib.sha256`` call made over exactly ``payload``.

    A spy, not a stub: the real digest is still returned, so nothing downstream
    changes. Only calls carrying the image bytes are recorded — other sha256 use
    on the analyze path is none of this test's business.
    """
    seen: list[bytes] = []
    real = hashlib.sha256

    def spy(data: Any = b"", **kwargs: Any) -> Any:
        if isinstance(data, bytes | bytearray) and bytes(data) == payload:
            seen.append(bytes(data))
        return real(data, **kwargs)

    with patch("publisher_v2.web.service.hashlib.sha256", spy):
        yield seen


async def test_analyze_does_not_hash_the_image_when_voice_matching_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The default tenant must not pay for a seed nobody will use.

    Voice matching is off unless a profile is configured, and `_select_voice_examples`
    then returns ``None`` before it ever looks at the seed. Hashing a multi-MB image
    to build that discarded seed is pure cost on every analyze request. The workflow
    call site guards on the feature flag before computing anything; the web path must
    end up equally lazy.

    Deliberately behavioural: any fix works — hoisting the flag check, or making the
    seed lazy — as long as no digest of the image bytes is computed.
    """
    service = _make_service(monkeypatch, profile=None)
    service.storage.download_image = AsyncMock(return_value=IMAGE_A)

    with (
        _sha256_calls_over(IMAGE_A) as hashed,
        patch("publisher_v2.services.sidecar.generate_and_upload_sidecar", new=AsyncMock(return_value=1.0)),
    ):
        await service.analyze_and_caption(FILENAME)

    call = service.ai_service.create_multi_caption_pair_from_analysis.await_args
    assert call is not None, "the caption call never happened"
    assert call.kwargs["voice_examples"] is None, "voice matching is off; there should be nothing to pass"
    assert hashed == [], (
        "the image bytes were hashed to seed a voice sample that was then discarded — "
        "compute the seed only when voice matching is actually on"
    )


async def test_analyze_still_hashes_the_image_when_voice_matching_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positive control: the laziness must not cost the bytes seed when it is needed."""
    service = _make_service(monkeypatch)
    service.storage.download_image = AsyncMock(return_value=IMAGE_A)

    with (
        _sha256_calls_over(IMAGE_A) as hashed,
        patch("publisher_v2.services.sidecar.generate_and_upload_sidecar", new=AsyncMock(return_value=1.0)),
    ):
        await service.analyze_and_caption(FILENAME)

    call = service.ai_service.create_multi_caption_pair_from_analysis.await_args
    assert call is not None, "the caption call never happened"
    assert hashed, "the image bytes were never hashed, so the seed cannot be the bytes digest"
    assert call.kwargs["voice_examples"] == sample_voice_examples(
        PROFILE, seed_source=hashlib.sha256(IMAGE_A).hexdigest(), platform_tags=None, platforms=["telegram"]
    )


async def test_analyze_seeds_on_the_filename_on_the_presigned_url_vision_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``vision_max_dimension == 0``: no download happens, so the name is all there is.

    The inverse of the bytes-branch test above. Swapping the file behind the name
    cannot change the sample here, because nothing on this path ever looks at the
    bytes — asserting that is what makes the two tests a genuine discrimination
    between the branches rather than two tests one implementation could satisfy.
    """
    service = _make_service(monkeypatch, vision_max_dimension=0)
    expected = sample_voice_examples(PROFILE, seed_source=FILENAME, platform_tags=None, platforms=["telegram"])

    first = await _voice_examples_for(service, IMAGE_A)
    second = await _voice_examples_for(service, IMAGE_B)

    service.storage.download_image.assert_not_awaited()
    assert first == expected, "the presigned-URL path did not seed on the filename"
    assert first == second, (
        "two different images under one name produced different samples on a path "
        "that never downloads the image — the seed came from somewhere it should not have"
    )
