from __future__ import annotations

import pytest

from publisher_v2.config.schema import ApplicationConfig, DropboxConfig, OpenAIConfig, PlatformsConfig, ContentConfig, FeaturesConfig
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService
from publisher_v2.services.storage import DropboxStorage
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.core.exceptions import StorageError


class _DummyStorage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def move_image_with_sidecars(self, folder: str, filename: str, target_subfolder: str) -> None:
        self.calls.append((folder, filename, target_subfolder))


class _DummyAI(AIService):
    def __init__(self) -> None:  # pragma: no cover - not used for curation
        self.analyzer = None
        self.generator = None


class _DummyPublisher(Publisher):
    async def publish(self, *args, **kwargs):  # pragma: no cover - not used for curation
        raise RuntimeError("should not be called in keep/remove tests")


def _base_config() -> ApplicationConfig:
    return ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k",
            app_secret="s",
            refresh_token="r",
            image_folder="/Photos",
            archive_folder="archive",
            folder_keep="keep",
            folder_remove="remove",
        ),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(),
        features=FeaturesConfig(),
        content=ContentConfig(hashtag_string="", archive=True, debug=False),
    )


@pytest.mark.asyncio
async def test_keep_image_calls_storage_with_configured_folder() -> None:
    cfg = _base_config()
    storage = _DummyStorage()
    orchestrator = WorkflowOrchestrator(cfg, storage, _DummyAI(), [])

    await orchestrator.keep_image("image.jpg", preview_mode=False, dry_run=False)

    assert storage.calls == [("/Photos", "image.jpg", "keep")]


@pytest.mark.asyncio
async def test_remove_image_calls_storage_with_configured_folder() -> None:
    cfg = _base_config()
    storage = _DummyStorage()
    orchestrator = WorkflowOrchestrator(cfg, storage, _DummyAI(), [])

    await orchestrator.remove_image("image.jpg", preview_mode=False, dry_run=False)

    assert storage.calls == [("/Photos", "image.jpg", "remove")]


@pytest.mark.asyncio
async def test_keep_remove_preview_mode_uses_preview_helper(capsys) -> None:
    cfg = _base_config()
    storage = _DummyStorage()
    orchestrator = WorkflowOrchestrator(cfg, storage, _DummyAI(), [])

    await orchestrator.keep_image("image.jpg", preview_mode=True, dry_run=False)
    captured = capsys.readouterr().out
    assert "CURATION ACTION (PREVIEW)" in captured
    assert "Action:   keep" in captured
    # No storage calls in preview
    assert storage.calls == []


@pytest.mark.asyncio
async def test_keep_remove_feature_disabled_raises() -> None:
    cfg = _base_config()
    cfg.features.keep_enabled = False
    cfg.features.remove_enabled = False
    storage = _DummyStorage()
    orchestrator = WorkflowOrchestrator(cfg, storage, _DummyAI(), [])

    with pytest.raises(StorageError):
        await orchestrator.keep_image("image.jpg")
    with pytest.raises(StorageError):
        await orchestrator.remove_image("image.jpg")


