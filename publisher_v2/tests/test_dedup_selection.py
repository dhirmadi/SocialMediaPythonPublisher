from __future__ import annotations

import hashlib
import json

import pytest

from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
)
from publisher_v2.utils.state import _cache_path

# Use centralized test fixtures from conftest.py (QC-001)
from conftest import BaseDummyStorage, BaseDummyAI, BaseDummyPublisher


class DedupTestStorage(BaseDummyStorage):
    """Storage with configurable content for dedup testing."""
    def __init__(self, content: bytes) -> None:
        super().__init__(content=content)
        self._images = ["a.jpg", "b.jpg"]


class DisabledPublisher(BaseDummyPublisher):
    """Publisher that is disabled and should never be called."""
    def __init__(self) -> None:
        super().__init__(platform="noop", enabled=False)
    
    async def publish(self, image_path: str, caption: str, context=None):
        raise AssertionError("should not publish in debug")


@pytest.mark.asyncio
async def test_dedup_skips_already_posted(monkeypatch, tmp_path):
    # Seed cache with hash of our content
    content = b"samebytes"
    h = hashlib.sha256(content).hexdigest()
    cache = _cache_path()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps([h]))

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
    storage = DedupTestStorage(content)
    ai = BaseDummyAI()
    orch = WorkflowOrchestrator(cfg, storage, ai, [DisabledPublisher()])
    result = await orch.execute()
    assert result.success is False
    assert result.error and "No new images" in result.error


