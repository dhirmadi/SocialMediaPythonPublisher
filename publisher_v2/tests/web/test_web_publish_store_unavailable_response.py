"""PUB-047 #186 / AC8 supplementary guard: the web ``/publish`` call site does not 500.

AC8's final clause states that because ``PublishStoreUnavailableError`` is caught
inside ``WorkflowOrchestrator.execute()``, ``WebImageService.publish_image`` (the
``/publish`` route's only call site) gets a normal ``PublishResponse`` with
``any_success=False`` and an empty ``results`` dict — not a 500 and not an escaping
exception. Nothing else in the suite guards that clause, so a future change that
re-raised the error out of ``execute()``, or added an ``any_success=False`` -> HTTP
error mapping, would go unnoticed.

The only fake is the publish store (the Postgres boundary) and ``telegram.Bot``
(the external Telegram client, the web harness's recording fake) — the latter so that a
regression which *did* publish is caught by its send log instead of touching the network.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from caption_pipeline_fakes import BaseDummyStorage, make_app_config, stub_ai_service

from publisher_v2.config.schema import (
    ApplicationConfig,
    TelegramConfig,
)
from publisher_v2.core.models import ImageAnalysis
from publisher_v2.db.publish_store import PublishStore
from publisher_v2.web.models import PublishResponse
from publisher_v2.web.service import WebImageService

from .conftest import _FakeBot


class _DummyAnalyzer:
    async def analyze(self, url_or_bytes: str | bytes) -> Any:
        return ImageAnalysis(description="Test", mood="neutral", tags=["t"], nsfw=False, safety_labels=[]), None


class _DummyGenerator:
    async def generate(self, analysis: Any, spec: Any) -> tuple[str, None]:
        return "hello world", None


def _config() -> ApplicationConfig:
    return make_app_config(
        platforms={"telegram_enabled": True},
        telegram=TelegramConfig(bot_token="tg-token", channel_id="@chan"),
        content={"archive": True},
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

    _FakeBot.sent = []
    with patch("publisher_v2.services.publishers.telegram.telegram.Bot", _FakeBot):
        service = WebImageService()
        service.storage = BaseDummyStorage(images=["test.jpg"])  # type: ignore[assignment]
        service.ai_service = stub_ai_service(_DummyAnalyzer(), _DummyGenerator())
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
    assert _FakeBot.sent == [], "no platform may be published when the publish store is unavailable"
