from __future__ import annotations

import pytest
from caption_pipeline_fakes import make_app_config

from publisher_v2.config.schema import (
    FeaturesConfig,
)
from publisher_v2.web.service import WebImageService


class _DummyOrchestrator:
    def __init__(self) -> None:
        self.keep_calls: list[str] = []
        self.remove_calls: list[str] = []

    async def keep_image(self, filename: str, *, preview_mode: bool = False, dry_run: bool = False) -> None:
        self.keep_calls.append(filename)

    async def remove_image(self, filename: str, *, preview_mode: bool = False, dry_run: bool = False) -> None:
        self.remove_calls.append(filename)


@pytest.fixture
def web_service_keep_remove(monkeypatch: pytest.MonkeyPatch) -> WebImageService:
    cfg = make_app_config(
        dropbox={"folder_keep": "keep", "folder_remove": "remove"},
        storage_paths={"folder_keep": "keep", "folder_remove": "remove"},
        features=FeaturesConfig(),
        content={"archive": True},
    )
    monkeypatch.setenv("DROPBOX_APP_KEY", "k")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "s")
    monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "r")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("FEATURE_ANALYZE_CAPTION", "true")
    monkeypatch.setenv("FEATURE_PUBLISH", "true")

    # Bypass loader and heavy collaborators
    monkeypatch.setattr(
        "publisher_v2.web.service.load_application_config",
        lambda config_path, env_path: cfg,
    )

    svc = WebImageService()
    # #91 (SEC-11): curation validates against the image listing.
    from unittest.mock import AsyncMock as _AsyncMock

    svc.storage.list_images = _AsyncMock(return_value=["image.jpg"])  # type: ignore[method-assign]
    orchestrator = _DummyOrchestrator()
    svc.orchestrator = orchestrator  # type: ignore[assignment]
    return svc


@pytest.mark.asyncio
async def test_web_keep_image_delegates_to_orchestrator(web_service_keep_remove: WebImageService) -> None:
    svc = web_service_keep_remove
    orchestrator: _DummyOrchestrator = svc.orchestrator  # type: ignore[assignment]

    resp = await svc.keep_image("image.jpg")

    assert orchestrator.keep_calls == ["image.jpg"]
    assert resp.filename == "image.jpg"
    assert resp.action == "keep"
    assert resp.destination_folder == "keep"


@pytest.mark.asyncio
async def test_web_remove_image_delegates_to_orchestrator(web_service_keep_remove: WebImageService) -> None:
    svc = web_service_keep_remove
    orchestrator: _DummyOrchestrator = svc.orchestrator  # type: ignore[assignment]

    resp = await svc.remove_image("image.jpg")

    assert orchestrator.remove_calls == ["image.jpg"]
    assert resp.filename == "image.jpg"
    assert resp.action == "remove"
    assert resp.destination_folder == "remove"


@pytest.mark.asyncio
async def test_web_keep_remove_disabled_raises_permission(web_service_keep_remove: WebImageService) -> None:
    svc = web_service_keep_remove
    svc.config.features.keep_enabled = False
    svc.config.features.remove_enabled = False

    with pytest.raises(PermissionError):
        await svc.keep_image("image.jpg")
    with pytest.raises(PermissionError):
        await svc.remove_image("image.jpg")
