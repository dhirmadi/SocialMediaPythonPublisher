from __future__ import annotations

import pytest
from caption_pipeline_fakes import make_app_config, stub_ai_service

from publisher_v2.core.exceptions import StorageError
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.publishers.base import Publisher


class _DummyStorage:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str]] = []

    async def move_image_with_sidecars(self, folder: str, filename: str, target_subfolder: str) -> None:
        self.calls.append((folder, filename, target_subfolder))


class _DummyPublisher(Publisher):
    async def publish(self, *args, **kwargs):  # pragma: no cover - not used for curation
        raise RuntimeError("should not be called in keep/remove tests")


@pytest.mark.asyncio
async def test_keep_image_calls_storage_with_configured_folder() -> None:
    cfg = make_app_config(
        dropbox={"folder_remove": "remove"}, storage_paths={"folder_remove": "remove"}, content={"archive": True}
    )
    storage = _DummyStorage()
    orchestrator = WorkflowOrchestrator(cfg, storage, stub_ai_service(), [])  # type: ignore[arg-type]

    await orchestrator.keep_image("image.jpg", preview_mode=False, dry_run=False)

    assert storage.calls == [("/Photos", "image.jpg", "keep")]


@pytest.mark.asyncio
async def test_remove_image_calls_storage_with_configured_folder() -> None:
    cfg = make_app_config(
        dropbox={"folder_remove": "remove"}, storage_paths={"folder_remove": "remove"}, content={"archive": True}
    )
    storage = _DummyStorage()
    orchestrator = WorkflowOrchestrator(cfg, storage, stub_ai_service(), [])  # type: ignore[arg-type]

    await orchestrator.remove_image("image.jpg", preview_mode=False, dry_run=False)

    assert storage.calls == [("/Photos", "image.jpg", "remove")]


@pytest.mark.asyncio
async def test_keep_remove_preview_mode_uses_preview_helper(capsys, caplog) -> None:
    # #96: preview curation no longer print()s via preview helper; it emits log_json only
    import logging

    cfg = make_app_config(
        dropbox={"folder_remove": "remove"}, storage_paths={"folder_remove": "remove"}, content={"archive": True}
    )
    storage = _DummyStorage()
    orchestrator = WorkflowOrchestrator(cfg, storage, stub_ai_service(), [])  # type: ignore[arg-type]

    with caplog.at_level(logging.INFO, logger="publisher_v2.workflow"):
        await orchestrator.keep_image("image.jpg", preview_mode=True, dry_run=False)
    assert capsys.readouterr().out == ""
    assert any("workflow_curation_preview" in rec.getMessage() for rec in caplog.records)
    # No storage calls in preview
    assert storage.calls == []


@pytest.mark.asyncio
async def test_keep_remove_feature_disabled_raises() -> None:
    cfg = make_app_config(
        dropbox={"folder_remove": "remove"}, storage_paths={"folder_remove": "remove"}, content={"archive": True}
    )
    cfg.features.keep_enabled = False
    cfg.features.remove_enabled = False
    storage = _DummyStorage()
    orchestrator = WorkflowOrchestrator(cfg, storage, stub_ai_service(), [])  # type: ignore[arg-type]

    with pytest.raises(StorageError):
        await orchestrator.keep_image("image.jpg")
    with pytest.raises(StorageError):
        await orchestrator.remove_image("image.jpg")
