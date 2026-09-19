"""REL-5 (#86): credential failures back off instead of mutating shared config."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    ManagedStorageConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
)
from publisher_v2.config.source import RuntimeConfig
from publisher_v2.core.exceptions import CredentialResolutionError


def _runtime_config() -> RuntimeConfig:
    cfg = ApplicationConfig(
        managed=ManagedStorageConfig(
            access_key_id="k", secret_access_key="s", endpoint_url="https://r2.local", bucket="b"
        ),
        storage_paths=StoragePathConfig(image_folder="/Photos"),
        openai=OpenAIConfig(api_key=None),
        platforms=PlatformsConfig(),
        content=ContentConfig(hashtag_string="", archive=True, debug=False),
    )
    return RuntimeConfig(
        host="a.example.test",
        tenant="a",
        config=cfg,
        credentials_refs={"openai": "ref-openai"},
    )


class _FakeSource:
    """ConfigSource double: fails credential resolution N times, then succeeds."""

    def __init__(self, failures: int) -> None:
        self._failures = failures
        self.calls = 0

    async def get_credentials(self, host: str, ref: str, tenant: str | None = None) -> dict:
        self.calls += 1
        if self.calls <= self._failures:
            raise CredentialResolutionError("upstream 503")
        return {"provider": "openai", "version": "1", "api_key": "sk-resolved"}


def _make_service(source: _FakeSource, runtime: RuntimeConfig):
    with patch("publisher_v2.web.service.create_storage") as fake_storage:
        fake_storage.return_value = AsyncMock()
        from publisher_v2.web.service import WebImageService

        return WebImageService(runtime=runtime, config_source=source)  # type: ignore[arg-type]


class TestAiCredentialBackoff:
    async def test_failure_does_not_mutate_runtime_config(self) -> None:
        runtime = _runtime_config()
        source = _FakeSource(failures=10)
        service = _make_service(source, runtime)

        ai = await service._ensure_ai_service()

        assert ai is None
        # The orchestrator's cached runtime config object must stay untouched.
        assert runtime.config.features.analyze_caption_enabled is True

    async def test_backoff_suppresses_immediate_retry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_now = {"t": 1000.0}
        monkeypatch.setattr("publisher_v2.web.service.time.monotonic", lambda: fake_now["t"])

        runtime = _runtime_config()
        source = _FakeSource(failures=1)
        service = _make_service(source, runtime)

        assert await service._ensure_ai_service() is None
        assert source.calls == 1
        # Within the backoff window: no new resolution attempt.
        fake_now["t"] += 10
        assert await service._ensure_ai_service() is None
        assert source.calls == 1

    async def test_resolution_retries_after_backoff_expires(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_now = {"t": 1000.0}
        monkeypatch.setattr("publisher_v2.web.service.time.monotonic", lambda: fake_now["t"])

        runtime = _runtime_config()
        source = _FakeSource(failures=1)
        service = _make_service(source, runtime)

        assert await service._ensure_ai_service() is None
        fake_now["t"] += 61
        ai = await service._ensure_ai_service()

        assert ai is not None
        assert source.calls == 2
        assert runtime.config.features.analyze_caption_enabled is True
        # The resolved key lives only on the service's own deep copy.
        assert runtime.config.openai.api_key is None
