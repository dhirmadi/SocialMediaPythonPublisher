from __future__ import annotations

import pytest
from caption_pipeline_fakes import make_app_config, stub_ai_service

from publisher_v2.core.exceptions import StorageError
from publisher_v2.core.workflow import WorkflowOrchestrator


class _DummyStorage:
    def __init__(self) -> None:
        self.delete_calls: list[tuple[str, str]] = []

    async def delete_file_with_sidecar(self, folder: str, filename: str) -> None:
        self.delete_calls.append((folder, filename))


@pytest.mark.asyncio
async def test_delete_image_calls_storage() -> None:
    cfg = make_app_config(
        dropbox={"folder_remove": "remove"}, features={"delete_enabled": True}, content={"archive": True}
    )
    storage = _DummyStorage()
    orchestrator = WorkflowOrchestrator(cfg, storage, stub_ai_service(), [])  # type: ignore[arg-type]

    await orchestrator.delete_image("image.jpg", preview_mode=False, dry_run=False)

    assert storage.delete_calls == [("/Photos", "image.jpg")]


@pytest.mark.parametrize(
    ("preview_mode", "dry_run"),
    [
        pytest.param(True, False, id="delete_image_preview_mode_does_not_call_storage"),
        pytest.param(False, True, id="delete_image_dry_run_does_not_call_storage"),
    ],
)
@pytest.mark.asyncio
async def test_delete_image_side_effect_free_modes_do_not_call_storage(preview_mode, dry_run) -> None:
    cfg = make_app_config(
        dropbox={"folder_remove": "remove"}, features={"delete_enabled": True}, content={"archive": True}
    )
    storage = _DummyStorage()
    orchestrator = WorkflowOrchestrator(cfg, storage, stub_ai_service(), [])  # type: ignore[arg-type]

    await orchestrator.delete_image("image.jpg", preview_mode=preview_mode, dry_run=dry_run)

    assert storage.delete_calls == []


@pytest.mark.asyncio
async def test_delete_image_feature_disabled_raises() -> None:
    cfg = make_app_config(
        dropbox={"folder_remove": "remove"}, features={"delete_enabled": False}, content={"archive": True}
    )
    storage = _DummyStorage()
    orchestrator = WorkflowOrchestrator(cfg, storage, stub_ai_service(), [])  # type: ignore[arg-type]

    with pytest.raises(StorageError, match="Delete feature is disabled"):
        await orchestrator.delete_image("image.jpg")
