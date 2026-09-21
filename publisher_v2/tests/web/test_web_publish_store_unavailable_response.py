"""PUB-047 #186 / AC8 supplementary guard: the web ``/publish`` call site does not 500.

AC8's final clause states that because ``PublishStoreUnavailableError`` is caught
inside ``WorkflowOrchestrator.execute()``, ``WebImageService.publish_image`` (the
``/publish`` route's only call site) gets a normal ``PublishResponse`` with
``any_success=False`` and an empty ``results`` dict — not a 500 and not an escaping
exception. Nothing else in the suite guards that clause, so a future change that
re-raised the error out of ``execute()``, or added an ``any_success=False`` -> HTTP
error mapping, would go unnoticed.

The only fake is the publish store (the Postgres boundary) and ``telegram.Bot``
(the external Telegram client) — the latter exists purely so that a regression
which *did* publish fails loudly instead of touching the network.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from conftest import BaseDummyStorage

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
    TelegramConfig,
)
from publisher_v2.core.models import ImageAnalysis
from publisher_v2.db.publish_store import PublishStore
from publisher_v2.services.ai import AIService
from publisher_v2.web.models import PublishResponse
from publisher_v2.web.service import WebImageService


@pytest.fixture(autouse=True)
def _isolated_posted_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """File-based posted state must not leak between tests (random test order)."""
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))


class _DummyAnalyzer:
    async def analyze(self, url_or_bytes: str | bytes) -> Any:
        return ImageAnalysis(description="Test", mood="neutral", tags=["t"], nsfw=False, safety_labels=[]), None


class _DummyGenerator:
    async def generate(self, analysis: Any, spec: Any) -> tuple[str, None]:
        return "hello world", None


class _DummyAI(AIService):
    def __init__(self) -> None:
        self.analyzer = _DummyAnalyzer()  # type: ignore[assignment]
        self.generator = _DummyGenerator()  # type: ignore[assignment]

        class _NoopLimiter:
            async def __aenter__(self) -> None:
                return None

            async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
                return False

        self._rate_limiter = _NoopLimiter()  # type: ignore[assignment]


class _ExplodingBot:
    """Stand-in for ``telegram.Bot``: any send here means the fail-closed path broke."""

    def __init__(self, token: str) -> None:
        self.token = token

    async def send_photo(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no platform may be published when the publish store is unavailable")

    async def shutdown(self) -> None:
        return None


def _config() -> ApplicationConfig:
    return ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        ),
        storage_paths=StoragePathConfig(image_folder="/Photos"),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(telegram_enabled=True, instagram_enabled=False, email_enabled=False),
        telegram=TelegramConfig(bot_token="tg-token", channel_id="@chan"),
        content=ContentConfig(hashtag_string="", archive=True, debug=False),
    )


async def test_publish_image_returns_empty_publish_response_when_publish_store_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8 (web clause): a raising publish store yields any_success=False/results={}, never a 500."""
    monkeypatch.setattr(
        "publisher_v2.web.service.load_application_config",
        lambda config_path, env_path: _config(),
    )

    store = AsyncMock(spec=PublishStore)
    store.posted_platforms.return_value = set()
    store.acquire_lease.side_effect = RuntimeError("publish store connection reset")

    with patch("publisher_v2.services.publishers.telegram.telegram.Bot", _ExplodingBot):
        service = WebImageService()
        service.storage = BaseDummyStorage(images=["test.jpg"])  # type: ignore[assignment]
        service.ai_service = _DummyAI()
        # Inject at the Postgres boundary: the service built itself without a DB,
        # so drop the cached orchestrator and let it be rebuilt around the fake store.
        service._publish_store = store
        service.orchestrator = None

        response = await service.publish_image("test.jpg", caption_override="A caption.")

    # Proof the claim path was actually reached — without this the assertions
    # below would also hold for a run that never consulted the publish store.
    store.acquire_lease.assert_awaited()
    assert isinstance(response, PublishResponse)
    assert response.filename == "test.jpg"
    assert response.any_success is False
    assert response.results == {}
    assert response.archived is False
    storage: BaseDummyStorage = service.storage  # type: ignore[assignment]
    assert storage.archives == 0
