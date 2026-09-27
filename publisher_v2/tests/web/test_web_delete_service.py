from __future__ import annotations

import pytest
from caption_pipeline_fakes import make_app_config

from publisher_v2.config.schema import (
    ApplicationConfig,
    FeaturesConfig,
)
from publisher_v2.web.service import WebImageService


class _DummyOrchestrator:
    def __init__(self) -> None:
        self.delete_calls: list[str] = []
        self.keep_calls: list[str] = []
        self.remove_calls: list[str] = []

    async def delete_image(self, filename: str, *, preview_mode: bool = False, dry_run: bool = False) -> None:
        self.delete_calls.append(filename)

    async def keep_image(self, filename: str, *, preview_mode: bool = False, dry_run: bool = False) -> None:
        self.keep_calls.append(filename)

    async def remove_image(self, filename: str, *, preview_mode: bool = False, dry_run: bool = False) -> None:
        self.remove_calls.append(filename)


def _make_config(*, delete_enabled: bool = True) -> ApplicationConfig:
    return make_app_config(
        dropbox={"folder_keep": "keep", "folder_remove": "remove"},
        features=FeaturesConfig(delete_enabled=delete_enabled),
        content={"archive": True},
    )


@pytest.fixture
def web_service_with_orchestrator(monkeypatch: pytest.MonkeyPatch) -> WebImageService:
    """Standalone-mode service with a dummy orchestrator injected."""
    cfg = _make_config()

    monkeypatch.setenv("DROPBOX_APP_KEY", "k")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "s")
    monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "r")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("FEATURE_ANALYZE_CAPTION", "true")
    monkeypatch.setenv("FEATURE_PUBLISH", "true")

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
async def test_web_delete_image_delegates_to_orchestrator(web_service_with_orchestrator: WebImageService) -> None:
    svc = web_service_with_orchestrator
    orchestrator: _DummyOrchestrator = svc.orchestrator  # type: ignore[assignment]

    resp = await svc.delete_image("image.jpg")

    assert orchestrator.delete_calls == ["image.jpg"]
    assert resp.filename == "image.jpg"
    assert resp.action == "delete"
    assert resp.destination_folder == ""


@pytest.mark.asyncio
async def test_web_delete_image_disabled_raises_permission(web_service_with_orchestrator: WebImageService) -> None:
    svc = web_service_with_orchestrator
    svc.config.features.delete_enabled = False

    with pytest.raises(PermissionError, match="Delete feature is disabled"):
        await svc.delete_image("image.jpg")


@pytest.mark.asyncio
async def test_web_delete_lazy_inits_orchestrator_when_none(web_service_with_orchestrator: WebImageService) -> None:
    """
    Reproduces GH-56: in orchestrator mode self.orchestrator starts as None.
    delete_image must call _ensure_orchestrator() so it gets lazily created.
    """
    svc = web_service_with_orchestrator
    svc.orchestrator = None  # type: ignore[assignment]

    dummy = _DummyOrchestrator()

    async def fake_ensure() -> _DummyOrchestrator:
        svc.orchestrator = dummy  # type: ignore[assignment]
        return dummy

    svc._ensure_orchestrator = fake_ensure  # type: ignore[assignment]

    resp = await svc.delete_image("image.jpg")

    assert dummy.delete_calls == ["image.jpg"]
    assert resp.action == "delete"


@pytest.mark.asyncio
async def test_web_keep_lazy_inits_orchestrator_when_none(web_service_with_orchestrator: WebImageService) -> None:
    """keep_image must also call _ensure_orchestrator() — same latent bug as delete."""
    svc = web_service_with_orchestrator
    svc.orchestrator = None  # type: ignore[assignment]

    dummy = _DummyOrchestrator()

    async def fake_ensure() -> _DummyOrchestrator:
        svc.orchestrator = dummy  # type: ignore[assignment]
        return dummy

    svc._ensure_orchestrator = fake_ensure  # type: ignore[assignment]

    resp = await svc.keep_image("image.jpg")

    assert dummy.keep_calls == ["image.jpg"]
    assert resp.action == "keep"


@pytest.mark.asyncio
async def test_web_remove_lazy_inits_orchestrator_when_none(web_service_with_orchestrator: WebImageService) -> None:
    """remove_image must also call _ensure_orchestrator() — same latent bug as delete."""
    svc = web_service_with_orchestrator
    svc.orchestrator = None  # type: ignore[assignment]

    dummy = _DummyOrchestrator()

    async def fake_ensure() -> _DummyOrchestrator:
        svc.orchestrator = dummy  # type: ignore[assignment]
        return dummy

    svc._ensure_orchestrator = fake_ensure  # type: ignore[assignment]

    resp = await svc.remove_image("image.jpg")

    assert dummy.remove_calls == ["image.jpg"]
    assert resp.action == "remove"
