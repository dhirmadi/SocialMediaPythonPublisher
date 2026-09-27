from __future__ import annotations

import pytest
from caption_pipeline_fakes import (
    BaseDummyPublisher,
    BaseDummyStorage,
    MultiCaptionDummyGenerator,
    make_app_config,
    stub_ai_service,
)

from publisher_v2.core.workflow import WorkflowOrchestrator


class SelectableStorage(BaseDummyStorage):
    """Storage with multiple images for selection testing."""

    def __init__(self) -> None:
        super().__init__()
        self._images = ["x.jpg", "y.jpg"]

    async def download_image(self, folder: str, filename: str) -> bytes:
        return b"content-" + filename.encode()


@pytest.mark.asyncio
async def test_select_and_dry_publish_skip_real_publish(monkeypatch):
    cfg = make_app_config(content={"hashtag_string": "#h", "archive": True})
    storage = SelectableStorage()
    ai = stub_ai_service(generator=MultiCaptionDummyGenerator(caption="hello world #tags"))
    orch = WorkflowOrchestrator(cfg, storage, ai, [BaseDummyPublisher()])
    result = await orch.execute(select_filename="y.jpg", dry_publish=True)
    assert result.success is True
    assert result.image_name == "y.jpg"
    assert result.archived is False
    assert "dummy" in result.publish_results and result.publish_results["dummy"].success is True
