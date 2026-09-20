"""#134 review follow-up: the corrupt-sidecar warning must name the file.

The `source=` threading survived deletion from all three call sites with the
whole suite still green — failure mode (a): the fix was proven only by calling
the parser directly, never through the service that actually reads sidecars
off Dropbox.
"""

from __future__ import annotations

import contextlib
import logging
from unittest.mock import AsyncMock

import pytest

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    FeaturesConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
)
from publisher_v2.web.service import WebImageService

CORRUPT_SIDECAR = b"sd prompt\n\n# ---\n# caption_generated: {not parseable\n"


@pytest.fixture
def web_service(monkeypatch: pytest.MonkeyPatch) -> WebImageService:
    cfg = ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k",
            app_secret="s",
            refresh_token="r",
            image_folder="/Photos",
            archive_folder="archive",
        ),
        storage_paths=StoragePathConfig(image_folder="/Photos"),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(),
        features=FeaturesConfig(),
        content=ContentConfig(hashtag_string="", archive=True, debug=False),
    )
    monkeypatch.setattr(
        "publisher_v2.web.service.load_application_config",
        lambda config_path, env_path: cfg,
    )
    return WebImageService()


@pytest.mark.asyncio
async def test_a_corrupt_sidecar_warning_names_the_image_it_came_from(
    web_service: WebImageService, caplog: pytest.LogCaptureFixture
) -> None:
    svc = web_service
    svc.storage.list_images = AsyncMock(return_value=["IMG_0042.jpg"])  # type: ignore[method-assign]
    svc.storage.get_temporary_link = AsyncMock(return_value="https://dl.example/IMG_0042.jpg")  # type: ignore[method-assign]
    svc.storage.download_sidecar_if_exists = AsyncMock(return_value=CORRUPT_SIDECAR)  # type: ignore[method-assign]

    with caplog.at_level(logging.WARNING, logger="publisher_v2.services.sidecar_parser"):
        await svc.get_image_details("IMG_0042.jpg")

    warnings = [r.getMessage() for r in caplog.records if "sidecar_metadata_json_invalid" in r.getMessage()]
    assert warnings, "no warning was emitted for the corrupt sidecar"
    assert any("IMG_0042.jpg" in w for w in warnings), warnings


@pytest.mark.asyncio
async def test_the_analyze_cache_read_also_names_the_image(
    web_service: WebImageService, caplog: pytest.LogCaptureFixture
) -> None:
    """The second call site survived deletion of `source=` on its own."""
    svc = web_service
    svc.storage.list_images = AsyncMock(return_value=["IMG_0099.jpg"])  # type: ignore[method-assign]
    svc.storage.get_temporary_link = AsyncMock(return_value="https://dl.example/IMG_0099.jpg")  # type: ignore[method-assign]
    svc.storage.download_sidecar_if_exists = AsyncMock(return_value=CORRUPT_SIDECAR)  # type: ignore[method-assign]

    # The cache read happens before the AI path, which is not configured here.
    with (
        caplog.at_level(logging.WARNING, logger="publisher_v2.services.sidecar_parser"),
        contextlib.suppress(Exception),
    ):
        await svc.analyze_and_caption("IMG_0099.jpg")

    warnings = [r.getMessage() for r in caplog.records if "sidecar_metadata_json_invalid" in r.getMessage()]
    assert warnings, "the analyze cache read emitted no warning for the corrupt sidecar"
    assert any("IMG_0099.jpg" in w for w in warnings), warnings
