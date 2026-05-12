"""PUB-045 Part C: Feature flag and integration wiring tests.

Covers AC-C1..AC-C7: env var default, schema field, WebImageService wiring,
WorkflowOrchestrator.execute() flush, analyze_and_caption() flush, and preview
mode behavior.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# AC-C1: feature flag schema + loader
# ---------------------------------------------------------------------------


class TestFeatureStorageOpsMeteringFlag:
    def test_feature_storage_ops_metering_defaults_false(self) -> None:
        """AC-C1: schema default is False."""
        from publisher_v2.config.schema import FeaturesConfig

        cfg = FeaturesConfig()
        assert cfg.storage_ops_metering_enabled is False

    def test_feature_storage_ops_metering_parsed(self) -> None:
        """AC-C1: env var parsed via parse_bool_env."""
        from publisher_v2.config.loader import parse_bool_env

        assert parse_bool_env("true", False, var_name="FEATURE_STORAGE_OPS_METERING") is True
        assert parse_bool_env("false", False, var_name="FEATURE_STORAGE_OPS_METERING") is False
        assert parse_bool_env(None, False, var_name="FEATURE_STORAGE_OPS_METERING") is False


# ---------------------------------------------------------------------------
# Web service wiring AC-C2..C4, C6
# ---------------------------------------------------------------------------


def _make_managed_storage_mock() -> MagicMock:
    """A ManagedStorage-like double with drain_ops_count for the meter."""
    from publisher_v2.services.managed_storage import ManagedStorage

    storage = MagicMock(spec=ManagedStorage)
    storage.drain_ops_count = MagicMock(return_value=0)
    return storage


def _make_runtime(tenant: str = "tenant-A") -> MagicMock:
    runtime = MagicMock()
    runtime.tenant = tenant
    runtime.credentials_refs = {}
    return runtime


def _make_config_source_with_orchestrator() -> tuple[MagicMock, AsyncMock]:
    """Return (config_source, client) where client.post_usage is awaitable."""
    client = MagicMock()
    client.post_usage = AsyncMock(return_value={"ok": True})
    cs = MagicMock()
    cs.orchestrator_client = client
    return cs, client


def _build_web_service(
    storage_ops_enabled: bool,
    orchestrated: bool,
    *,
    managed: bool = True,
):
    """Build a WebImageService bypassing __init__ to avoid full config plumbing."""
    from publisher_v2.config.schema import (
        ApplicationConfig,
        ContentConfig,
        DropboxConfig,
        FeaturesConfig,
        ManagedStorageConfig,
        OpenAIConfig,
        PlatformsConfig,
        StoragePathConfig,
    )
    from publisher_v2.web.service import WebImageService

    cfg = ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k",
            app_secret="s",
            refresh_token="r",
            image_folder="/Photos",
            archive_folder="archive",
        ),
        managed=None,
        storage_paths=StoragePathConfig(image_folder="/Photos"),
        openai=OpenAIConfig(api_key="sk-test-key-for-testing"),
        platforms=PlatformsConfig(telegram_enabled=False, instagram_enabled=False, email_enabled=False),
        telegram=None,
        instagram=None,
        email=None,
        content=ContentConfig(hashtag_string="#x", archive=False, debug=False),
        features=FeaturesConfig(storage_ops_metering_enabled=storage_ops_enabled),
    )
    # Suppress unused-import warning when managed storage isn't needed in this path
    _ = ManagedStorageConfig

    svc = WebImageService.__new__(WebImageService)
    import logging as _logging

    svc.logger = _logging.getLogger("publisher_v2.web.test")
    svc.config = cfg
    svc.storage = _make_managed_storage_mock() if managed else MagicMock()
    svc.ai_service = None
    svc.publishers = []
    svc._image_cache = None
    svc._image_cache_expiry = None
    svc._image_cache_ttl_seconds = 1.0
    svc._recently_shown = []

    if orchestrated:
        runtime = _make_runtime()
        cs, _ = _make_config_source_with_orchestrator()
        svc._runtime = runtime
        svc._config_source = cs
    else:
        svc._runtime = None
        svc._config_source = None

    svc._usage_meter = None
    # Invoke the post-init hook that builds the meter (Part C wiring).
    svc._init_storage_ops_meter()
    svc.orchestrator = None
    return svc


class TestWebServiceWiring:
    def test_meter_not_created_when_flag_false(self) -> None:
        """AC-C2: feature disabled → no meter constructed."""
        svc = _build_web_service(storage_ops_enabled=False, orchestrated=True, managed=True)
        assert svc._storage_ops_meter is None

    def test_meter_created_when_flag_true_orchestrator_mode(self) -> None:
        """AC-C3: feature enabled + orchestrator mode + ManagedStorage → meter built."""
        from publisher_v2.services.storage_ops_meter import StorageOpsMeter

        svc = _build_web_service(storage_ops_enabled=True, orchestrated=True, managed=True)
        assert isinstance(svc._storage_ops_meter, StorageOpsMeter)

    def test_meter_none_in_standalone_mode(self) -> None:
        """AC-C4: standalone mode → meter is None regardless of flag."""
        svc = _build_web_service(storage_ops_enabled=True, orchestrated=False, managed=True)
        assert svc._storage_ops_meter is None

    def test_meter_none_when_storage_not_managed(self) -> None:
        """No ManagedStorage → meter not built (per spec wiring)."""
        svc = _build_web_service(storage_ops_enabled=True, orchestrated=True, managed=False)
        assert svc._storage_ops_meter is None

    async def test_analyze_and_caption_calls_flush(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-C6: analyze_and_caption() calls flush() after the analysis path."""
        svc = _build_web_service(storage_ops_enabled=True, orchestrated=True, managed=True)
        # Replace meter with an instrumented one
        meter = MagicMock()
        meter.flush = AsyncMock()
        svc._storage_ops_meter = meter

        # storage.get_temporary_link must be awaitable
        svc.storage.get_temporary_link = AsyncMock(return_value="https://link")
        svc.storage.download_sidecar_if_exists = AsyncMock(return_value=None)

        # Disable analyze feature path so we exit early but still hit the flush.
        svc.config.features.analyze_caption_enabled = False

        await svc.analyze_and_caption("img.jpg")
        meter.flush.assert_awaited()


# ---------------------------------------------------------------------------
# Workflow wiring AC-C5, C7
# ---------------------------------------------------------------------------


def _build_workflow(*, preview: bool, meter: MagicMock):
    """Helper to build a workflow that runs end-to-end with a mock storage."""
    from publisher_v2.config.schema import (
        ApplicationConfig,
        ContentConfig,
        DropboxConfig,
        FeaturesConfig,
        OpenAIConfig,
        PlatformsConfig,
        StoragePathConfig,
    )
    from publisher_v2.core.workflow import WorkflowOrchestrator

    cfg = ApplicationConfig(
        dropbox=DropboxConfig(
            app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
        ),
        storage_paths=StoragePathConfig(image_folder="/Photos", archive_folder="archive"),
        openai=OpenAIConfig(api_key="sk-test-key-for-testing"),
        platforms=PlatformsConfig(telegram_enabled=False, instagram_enabled=False, email_enabled=False),
        telegram=None,
        instagram=None,
        email=None,
        content=ContentConfig(hashtag_string="#x", archive=False, debug=False),
        features=FeaturesConfig(analyze_caption_enabled=False, publish_enabled=False),
    )

    storage = MagicMock()
    storage.supports_content_hashing = MagicMock(return_value=False)
    storage.list_images = AsyncMock(return_value=["test.jpg"])
    storage.download_image = AsyncMock(return_value=b"\x89PNG\r\n\x1a\n")
    storage.get_temporary_link = AsyncMock(return_value="https://link")

    ai_service = SimpleNamespace()

    wf = WorkflowOrchestrator(
        config=cfg,
        storage=storage,  # type: ignore[arg-type]
        ai_service=ai_service,  # type: ignore[arg-type]
        publishers=[],
        storage_ops_meter=meter,
    )
    return wf


class TestWorkflowWiring:
    async def test_execute_calls_flush_at_end(self, monkeypatch: pytest.MonkeyPatch, bypass_dedup: None) -> None:
        """AC-C5: WorkflowOrchestrator.execute() calls flush() at the end."""
        meter = MagicMock()
        meter.flush = AsyncMock()
        wf = _build_workflow(preview=False, meter=meter)

        await wf.execute()
        meter.flush.assert_awaited()

    async def test_preview_mode_still_flushes_meter(self, monkeypatch: pytest.MonkeyPatch, bypass_dedup: None) -> None:
        """AC-C7: preview mode still flushes the meter (R2 costs are real)."""
        meter = MagicMock()
        meter.flush = AsyncMock()
        wf = _build_workflow(preview=True, meter=meter)

        await wf.execute(preview_mode=True)
        meter.flush.assert_awaited()
