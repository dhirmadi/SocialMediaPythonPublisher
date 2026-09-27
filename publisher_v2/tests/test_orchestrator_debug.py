from __future__ import annotations

import json
import logging

import pytest
from caption_pipeline_fakes import (
    BaseDummyPublisher,
    BaseDummyStorage,
    MultiCaptionDummyGenerator,
    make_app_config,
    stub_ai_service,
)

from publisher_v2.core.workflow import WorkflowOrchestrator


@pytest.mark.asyncio
async def test_orchestrator_debug_mode_skips_publish_and_no_archive(tmp_path):
    cfg = make_app_config(content={"hashtag_string": "#tags", "archive": True, "debug": True})
    storage = BaseDummyStorage()
    ai = stub_ai_service(generator=MultiCaptionDummyGenerator(caption="hello world #tags"))
    publishers = [BaseDummyPublisher()]
    orchestrator = WorkflowOrchestrator(cfg, storage, ai, publishers)
    result = await orchestrator.execute()

    assert result.success is True
    assert result.archived is False
    assert result.image_name == "test.jpg"
    assert result.caption.startswith("hello world")
    assert "dummy" in result.publish_results
    assert result.publish_results["dummy"].success is True


@pytest.mark.asyncio
async def test_orchestrator_emits_timing_log(tmp_path, caplog: pytest.LogCaptureFixture) -> None:
    cfg = make_app_config(content={"hashtag_string": "#tags", "archive": True, "debug": True})
    storage = BaseDummyStorage()
    ai = stub_ai_service(generator=MultiCaptionDummyGenerator(caption="hello world #tags"))
    publishers = [BaseDummyPublisher()]
    orchestrator = WorkflowOrchestrator(cfg, storage, ai, publishers)  # type: ignore[arg-type]

    caplog.set_level(logging.INFO, logger="publisher_v2.workflow")

    await orchestrator.execute()

    records = [r for r in caplog.records if "workflow_timing" in r.getMessage()]
    assert records, "Expected a workflow_timing log entry"

    entry = json.loads(records[0].getMessage())
    assert entry.get("correlation_id")
    assert isinstance(entry.get("dropbox_list_images_ms"), int)
    assert isinstance(entry.get("image_selection_ms"), int)
    assert isinstance(entry.get("caption_generation_ms"), int)
