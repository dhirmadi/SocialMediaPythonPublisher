from __future__ import annotations

import pytest

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
)
from publisher_v2.core.workflow import WorkflowOrchestrator

# Use centralized test fixtures from conftest.py (QC-001)
from conftest import BaseDummyStorage, BaseDummyAI, BaseDummyPublisher


class SelectableStorage(BaseDummyStorage):
    """Storage with multiple images for selection testing."""
    def __init__(self) -> None:
        super().__init__()
        self._images = ["x.jpg", "y.jpg"]

    async def download_image(self, folder: str, filename: str) -> bytes:
        return b"content-" + filename.encode()


@pytest.mark.asyncio
async def test_select_and_dry_publish_skip_real_publish(monkeypatch):
    cfg = ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        ),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(telegram_enabled=False, instagram_enabled=False, email_enabled=False),
        telegram=None,
        instagram=None,
        email=None,
        content=ContentConfig(hashtag_string="#h", archive=True, debug=False),
    )
    # Use centralized fixtures (QC-001)
    storage = SelectableStorage()
    ai = BaseDummyAI()
    orch = WorkflowOrchestrator(cfg, storage, ai, [BaseDummyPublisher()])
    result = await orch.execute(select_filename="y.jpg", dry_publish=True)
    assert result.success is True
    assert result.image_name == "y.jpg"
    assert result.archived is False
    assert "dummy" in result.publish_results and result.publish_results["dummy"].success is True


