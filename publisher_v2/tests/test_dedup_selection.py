from __future__ import annotations

import hashlib
import json

import pytest

# Use centralized test fixtures from conftest.py (QC-001)
from conftest import BaseDummyAI, BaseDummyPublisher, BaseDummyStorage

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
)
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.utils.state import _cache_path


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
    # Seed cache with hash of our content (current dict schema).
    content = b"samebytes"
    h = hashlib.sha256(content).hexdigest()
    cache = _cache_path()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"hashes": [h]}))

    cfg = ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        ),
        storage_paths=StoragePathConfig(image_folder="/Photos"),
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


class TestSupportsContentHashingContract:
    """#95: the legacy (non-hashing) selection branch stays only for test
    doubles — both REAL backends must support content hashing, so production
    never takes it. This contract test is the condition for keeping it."""

    def test_dropbox_supports_content_hashing(self, monkeypatch) -> None:
        from unittest.mock import MagicMock, patch

        from publisher_v2.config.schema import DropboxConfig
        from publisher_v2.services.storage import DropboxStorage

        with patch("publisher_v2.services.storage.dropbox.Dropbox", MagicMock()):
            storage = DropboxStorage(
                DropboxConfig(app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos")
            )
        assert storage.supports_content_hashing() is True

    def test_managed_storage_supports_content_hashing(self) -> None:
        from publisher_v2.config.schema import ManagedStorageConfig
        from publisher_v2.services.managed_storage import ManagedStorage

        storage = ManagedStorage(
            ManagedStorageConfig(access_key_id="k", secret_access_key="s", endpoint_url="https://r2.local", bucket="b")
        )
        assert storage.supports_content_hashing() is True
