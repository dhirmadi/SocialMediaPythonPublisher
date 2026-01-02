from __future__ import annotations

import json
import logging

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


@pytest.mark.asyncio
async def test_orchestrator_debug_mode_skips_publish_and_no_archive(tmp_path):
    cfg = ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        ),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(telegram_enabled=False, instagram_enabled=False, email_enabled=False),
        telegram=None,
        instagram=None,
        email=None,
        content=ContentConfig(hashtag_string="#tags", archive=True, debug=True),
    )
    # Use centralized fixtures (QC-001)
    storage = BaseDummyStorage()
    ai = BaseDummyAI()
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
    cfg = ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        ),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(telegram_enabled=False, instagram_enabled=False, email_enabled=False),
        telegram=None,
        instagram=None,
        email=None,
        content=ContentConfig(hashtag_string="#tags", archive=True, debug=True),
    )
    # Use centralized fixtures (QC-001)
    storage = BaseDummyStorage()
    ai = BaseDummyAI()
    publishers = [BaseDummyPublisher()]
    orchestrator = WorkflowOrchestrator(cfg, storage, ai, publishers)

    caplog.set_level(logging.INFO, logger="publisher_v2.workflow")

    await orchestrator.execute()

    records = [r for r in caplog.records if "workflow_timing" in r.getMessage()]
    assert records, "Expected a workflow_timing log entry"

    entry = json.loads(records[0].getMessage())
    assert entry.get("correlation_id")
    assert isinstance(entry.get("dropbox_list_images_ms"), int)
    assert isinstance(entry.get("image_selection_ms"), int)
    assert isinstance(entry.get("caption_generation_ms"), int)


