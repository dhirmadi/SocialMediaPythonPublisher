from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
)
from publisher_v2.services.ai import AIService
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.services.storage import DropboxStorage
from publisher_v2.utils.state import _cache_path


class DummyStorageDup(DropboxStorage):
    def __init__(self, content: bytes):
        self._content = content
        self.config = DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        )

    async def list_images(self, folder: str):
        return ["a.jpg", "b.jpg"]

    async def download_image(self, folder: str, filename: str) -> bytes:
        return self._content

    async def get_temporary_link(self, folder: str, filename: str) -> str:
        return "https://example.com/tmp/x.jpg"

    async def archive_image(self, folder: str, filename: str, archive_folder: str) -> None:
        return None


class DummyAI2(AIService):
    def __init__(self):
        self._caption = "ok #h"

    async def create_caption(self, url_or_bytes: str | bytes, spec):
        return self._caption


class NoopPublisher(Publisher):
    @property
    def platform_name(self) -> str:
        return "noop"

    def is_enabled(self) -> bool:
        return False

    async def publish(self, image_path: str, caption: str):
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
    storage = DummyStorageDup(content)
    ai = DummyAI2()
    orch = WorkflowOrchestrator(cfg, storage, ai, [NoopPublisher()])
    result = await orch.execute()
    assert result.success is False
    assert result.error and "No new images" in result.error


