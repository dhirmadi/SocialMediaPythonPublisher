from __future__ import annotations

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
from publisher_v2.core.exceptions import StorageError
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.ai import AIService


class _DummyStorage:
    def __init__(self) -> None:
        self.delete_calls: list[tuple[str, str]] = []

    async def delete_file_with_sidecar(self, folder: str, filename: str) -> None:
        self.delete_calls.append((folder, filename))


class _DummyAI(AIService):
    def __init__(self) -> None:
        self.analyzer = None  # type: ignore[assignment]
        self.generator = None  # type: ignore[assignment]


def _base_config(*, delete_enabled: bool = True) -> ApplicationConfig:
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
        storage_paths=StoragePathConfig(image_folder="/Photos"),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(),
        features=FeaturesConfig(delete_enabled=delete_enabled),
        content=ContentConfig(hashtag_string="", archive=True, debug=False),
    )


@pytest.mark.asyncio
async def test_delete_image_calls_storage() -> None:
    cfg = _base_config()
    storage = _DummyStorage()
    orchestrator = WorkflowOrchestrator(cfg, storage, _DummyAI(), [])  # type: ignore[arg-type]

    await orchestrator.delete_image("image.jpg", preview_mode=False, dry_run=False)

    assert storage.delete_calls == [("/Photos", "image.jpg")]


@pytest.mark.asyncio
async def test_delete_image_preview_mode_does_not_call_storage() -> None:
    cfg = _base_config()
    storage = _DummyStorage()
    orchestrator = WorkflowOrchestrator(cfg, storage, _DummyAI(), [])  # type: ignore[arg-type]

    await orchestrator.delete_image("image.jpg", preview_mode=True, dry_run=False)

    assert storage.delete_calls == []


@pytest.mark.asyncio
async def test_delete_image_dry_run_does_not_call_storage() -> None:
    cfg = _base_config()
    storage = _DummyStorage()
    orchestrator = WorkflowOrchestrator(cfg, storage, _DummyAI(), [])  # type: ignore[arg-type]

    await orchestrator.delete_image("image.jpg", preview_mode=False, dry_run=True)

    assert storage.delete_calls == []


@pytest.mark.asyncio
async def test_delete_image_feature_disabled_raises() -> None:
    cfg = _base_config(delete_enabled=False)
    storage = _DummyStorage()
    orchestrator = WorkflowOrchestrator(cfg, storage, _DummyAI(), [])  # type: ignore[arg-type]

    with pytest.raises(StorageError, match="Delete feature is disabled"):
        await orchestrator.delete_image("image.jpg")
