"""#140: the analyze path must not buy a presigned link vision never uses.

Since #93 vision receives bytes whenever ``vision_max_dimension > 0``, so the
unconditional ``get_temporary_link`` on the analyze path was a billed storage op
per request with no consumer. Exercised through the real ``WebImageService``
against a storage double that counts protocol calls.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from publisher_v2.core.models import ImageAnalysis


class _CountingStorage:
    def __init__(self) -> None:
        self.temp_link_calls = 0
        self.download_calls = 0

    def supports_content_hashing(self) -> bool:
        return False

    async def list_images(self, folder: str) -> list[str]:
        return ["img.jpg"]

    async def get_temporary_link(self, folder: str, filename: str) -> str:
        self.temp_link_calls += 1
        return f"https://example.com/{filename}"

    async def download_image(self, folder: str, filename: str) -> bytes:
        self.download_calls += 1
        return b"\x89PNG\r\n\x1a\n"

    async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None:
        return None

    async def upload_sidecar(self, folder: str, filename: str, content: str) -> None:
        return None


class _Analyzer:
    async def analyze(self, source: str | bytes) -> Any:
        return ImageAnalysis(description="d", mood="m", tags=["t"], nsfw=False, safety_labels=[]), None


class _Generator:
    model = "gpt-test"

    async def generate(self, analysis: Any, spec: Any) -> tuple[str, None]:
        return "a caption", None


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch, tmp_path) -> Any:
    env = {
        "CONFIG_SOURCE": "env",
        "HOME": str(tmp_path),
        "STORAGE_PATHS": json.dumps({"root": "/Photos", "archive": "archive"}),
        "PUBLISHERS": json.dumps([{"type": "telegram", "channel_id": "@chan"}]),
        "TELEGRAM_BOT_TOKEN": "tg",
        "OPENAI_SETTINGS": json.dumps({"vision_max_dimension": 1024}),
        "OPENAI_API_KEY": "sk-test",
        "DROPBOX_APP_KEY": "k",
        "DROPBOX_APP_SECRET": "s",
        "DROPBOX_REFRESH_TOKEN": "r",
        "WEB_SESSION_SECRET": "test-secret",
        "FEATURE_ANALYZE_CAPTION": "true",
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    for key in ("ORCHESTRATOR_BASE_URL", "DATABASE_URL", "CONFIG_PATH"):
        monkeypatch.delenv(key, raising=False)

    from publisher_v2.config.source import get_config_source
    from publisher_v2.web.service import WebImageService

    get_config_source.cache_clear()
    svc = WebImageService()
    svc.storage = _CountingStorage()  # type: ignore[assignment]
    svc.ai_service.analyzer = _Analyzer()  # type: ignore[union-attr,assignment]
    svc.ai_service.generator = _Generator()  # type: ignore[union-attr,assignment]
    svc._orchestrator = None
    return svc


async def test_analyze_with_resizing_enabled_buys_no_temporary_link(service: Any) -> None:
    await service.analyze_and_caption("img.jpg")

    assert service.storage.temp_link_calls == 0
    assert service.storage.download_calls >= 1


async def test_analyze_still_uses_the_link_when_resizing_is_disabled(
    service: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """vision_max_dimension == 0 keeps the legacy presigned-URL path."""
    service.config.openai.vision_max_dimension = 0

    await service.analyze_and_caption("img.jpg")

    assert service.storage.temp_link_calls == 1
