"""
Tests for web/service.py uncovered paths (QC-003).

These tests cover the uncovered lines in WebImageService:
- Line 51: RuntimeError for missing CONFIG_PATH
- Lines 80-86: TTL parsing logic
- Lines 155-163: get_image_details exception handling
- Lines 199-211: get_thumbnail logic
- Lines 299-309: sd_caption error fallback
- Lines 337-339: sidecar write exception handling
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest


class TestWebImageServiceConfigPath:
    """Tests for CONFIG_PATH validation."""

    def test_raises_runtime_error_when_config_path_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Verify WebImageService raises ConfigurationError when CONFIG_PATH not set and not in env-first mode."""
        from publisher_v2.core.exceptions import ConfigurationError

        # Import first: web.service loads the workspace .env at module import
        # time, which would otherwise re-populate the vars we clear below.
        from publisher_v2.web.service import WebImageService

        # Keep the loader from re-loading the workspace .env inside the call.
        monkeypatch.setattr("publisher_v2.config.loader.load_dotenv", lambda *a, **k: None)
        # Ensure CONFIG_PATH is not set (and ENV_PATH cannot re-load the workspace .env)
        monkeypatch.delenv("CONFIG_PATH", raising=False)
        monkeypatch.delenv("ENV_PATH", raising=False)
        # Ensure not in env-first mode (no STORAGE_PATHS, PUBLISHERS, OPENAI_SETTINGS)
        monkeypatch.delenv("STORAGE_PATHS", raising=False)
        monkeypatch.delenv("PUBLISHERS", raising=False)
        monkeypatch.delenv("OPENAI_SETTINGS", raising=False)

        with pytest.raises(ConfigurationError, match="required env vars not set"):
            WebImageService()


class TestWebImageServiceTTLParsing:
    """Tests for TTL parsing logic (lines 80-86)."""

    def test_uses_env_ttl_when_valid(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """Verify WebImageService uses WEB_IMAGE_CACHE_TTL_SECONDS from env when valid."""
        monkeypatch.setenv("WEB_IMAGE_CACHE_TTL_SECONDS", "120")
        monkeypatch.setenv("STORAGE_PATHS", '{"root": "/Photos", "archive": "archive"}')
        monkeypatch.setenv("PUBLISHERS", "[]")
        monkeypatch.setenv("OPENAI_SETTINGS", "{}")
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        # Patch Dropbox client to avoid real API calls
        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.web.service import WebImageService

            service = WebImageService()
            # #91 (SEC-11): filename ops validate against the image listing.
            service.storage.list_images = AsyncMock(return_value=["test.jpg", "nonexistent.jpg"])  # type: ignore[method-assign]
            service.storage.download_image = AsyncMock(return_value=b"image-bytes")  # type: ignore[method-assign]

            assert service._image_cache_ttl_seconds == 120.0

    def test_uses_default_ttl_when_env_invalid(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """Verify WebImageService uses default TTL when env value is invalid."""
        monkeypatch.setenv("WEB_IMAGE_CACHE_TTL_SECONDS", "invalid")
        monkeypatch.setenv("STORAGE_PATHS", '{"root": "/Photos", "archive": "archive"}')
        monkeypatch.setenv("PUBLISHERS", "[]")
        monkeypatch.setenv("OPENAI_SETTINGS", "{}")
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.web.service import WebImageService

            service = WebImageService()
            # #91 (SEC-11): filename ops validate against the image listing.
            service.storage.list_images = AsyncMock(return_value=["test.jpg", "nonexistent.jpg"])  # type: ignore[method-assign]
            service.storage.download_image = AsyncMock(return_value=b"image-bytes")  # type: ignore[method-assign]

            # Should use the default from static config, not crash
            assert service._image_cache_ttl_seconds > 0

    def test_ignores_negative_env_ttl(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """Verify WebImageService ignores negative TTL values from env."""
        monkeypatch.setenv("WEB_IMAGE_CACHE_TTL_SECONDS", "-10")
        monkeypatch.setenv("STORAGE_PATHS", '{"root": "/Photos", "archive": "archive"}')
        monkeypatch.setenv("PUBLISHERS", "[]")
        monkeypatch.setenv("OPENAI_SETTINGS", "{}")
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.web.service import WebImageService

            service = WebImageService()
            # #91 (SEC-11): filename ops validate against the image listing.
            service.storage.list_images = AsyncMock(return_value=["test.jpg", "nonexistent.jpg"])  # type: ignore[method-assign]
            service.storage.download_image = AsyncMock(return_value=b"image-bytes")  # type: ignore[method-assign]

            # Should use the default from static config (>0), not negative value
            assert service._image_cache_ttl_seconds > 0


class TestGetImageDetailsExceptionHandling:
    """Tests for get_image_details exception handling (lines 155-163)."""

    @pytest.mark.asyncio
    async def test_raises_file_not_found_on_storage_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """Verify get_image_details raises FileNotFoundError on storage errors."""
        monkeypatch.setenv("STORAGE_PATHS", '{"root": "/Photos", "archive": "archive"}')
        monkeypatch.setenv("PUBLISHERS", "[]")
        monkeypatch.setenv("OPENAI_SETTINGS", "{}")
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.web.service import WebImageService

            service = WebImageService()
            # #91 (SEC-11): filename ops validate against the image listing.
            service.storage.list_images = AsyncMock(return_value=["test.jpg", "nonexistent.jpg"])  # type: ignore[method-assign]
            service.storage.download_image = AsyncMock(return_value=b"image-bytes")  # type: ignore[method-assign]

            # Mock storage to raise an error
            service.storage.get_temporary_link = AsyncMock(side_effect=Exception("Storage error"))  # type: ignore[method-assign]

            with pytest.raises(FileNotFoundError, match="not found"):
                await service.get_image_details("nonexistent.jpg")


class TestGetThumbnailSizeMapping:
    """Tests for get_thumbnail size mapping (lines 199-211)."""

    @pytest.mark.asyncio
    async def test_maps_known_thumbnail_sizes(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """Verify get_thumbnail correctly maps size strings to ThumbnailSize enums."""
        monkeypatch.setenv("STORAGE_PATHS", '{"root": "/Photos", "archive": "archive"}')
        monkeypatch.setenv("PUBLISHERS", "[]")
        monkeypatch.setenv("OPENAI_SETTINGS", "{}")
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.web.service import WebImageService

            service = WebImageService()
            # #91 (SEC-11): filename ops validate against the image listing.
            service.storage.list_images = AsyncMock(return_value=["test.jpg", "nonexistent.jpg"])  # type: ignore[method-assign]
            service.storage.download_image = AsyncMock(return_value=b"image-bytes")  # type: ignore[method-assign]

            # Mock storage get_thumbnail
            service.storage.get_thumbnail = AsyncMock(return_value=b"thumbnail_bytes")  # type: ignore[method-assign]

            # Test different size mappings
            for size_str in ["w256h256", "w480h320", "w640h480", "w960h640", "w1024h768"]:
                result = await service.get_thumbnail("test.jpg", size=size_str)
                assert result == b"thumbnail_bytes"

    @pytest.mark.asyncio
    async def test_defaults_to_w960h640_for_unknown_size(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """Verify get_thumbnail defaults to w960h640 for unknown size strings."""
        monkeypatch.setenv("STORAGE_PATHS", '{"root": "/Photos", "archive": "archive"}')
        monkeypatch.setenv("PUBLISHERS", "[]")
        monkeypatch.setenv("OPENAI_SETTINGS", "{}")
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.services.storage_protocol import ThumbnailSize
            from publisher_v2.web.service import WebImageService

            service = WebImageService()
            # #91 (SEC-11): filename ops validate against the image listing.
            service.storage.list_images = AsyncMock(return_value=["test.jpg", "nonexistent.jpg"])  # type: ignore[method-assign]
            service.storage.download_image = AsyncMock(return_value=b"image-bytes")  # type: ignore[method-assign]

            # Mock storage get_thumbnail
            service.storage.get_thumbnail = AsyncMock(return_value=b"thumbnail_bytes")  # type: ignore[method-assign]

            # Test unknown size
            result = await service.get_thumbnail("test.jpg", size="unknown_size")
            assert result == b"thumbnail_bytes"

            # Verify default size was used
            call_kwargs = service.storage.get_thumbnail.call_args.kwargs
            assert call_kwargs.get("size") == ThumbnailSize.W960H640


class TestAnalyzeAndCaptionSdCaptionFallback:
    """Tests for sd_caption error fallback (lines 299-309)."""

    @pytest.mark.asyncio
    async def test_falls_back_to_legacy_caption_on_sd_error(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """Verify analyze_and_caption falls back to legacy caption when sd_caption fails."""
        monkeypatch.setenv("STORAGE_PATHS", '{"root": "/Photos", "archive": "archive"}')
        monkeypatch.setenv("PUBLISHERS", "[]")
        monkeypatch.setenv("OPENAI_SETTINGS", "{}")
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.core.models import ImageAnalysis
            from publisher_v2.web.service import WebImageService

            service = WebImageService()
            # #91 (SEC-11): filename ops validate against the image listing.
            service.storage.list_images = AsyncMock(return_value=["test.jpg", "nonexistent.jpg"])  # type: ignore[method-assign]
            service.storage.download_image = AsyncMock(return_value=b"image-bytes")  # type: ignore[method-assign]

            # Mock storage methods
            service.storage.get_temporary_link = AsyncMock(return_value="http://temp")  # type: ignore[method-assign]
            service.storage.download_sidecar_if_exists = AsyncMock(return_value=None)  # type: ignore[method-assign]

            # Mock AI service - pair fails, fallback succeeds
            analysis = ImageAnalysis(
                description="Test",
                mood="neutral",
                tags=["test"],
                nsfw=False,
                safety_labels=[],
            )
            service.ai_service.analyzer.analyze = AsyncMock(return_value=(analysis, None))  # type: ignore[method-assign, union-attr]
            service.ai_service.create_caption_pair_from_analysis = AsyncMock(side_effect=Exception("SD caption failed"))  # type: ignore[method-assign, union-attr]
            # PUB-041 follow-up: fallback now uses create_caption_from_analysis (reuses
            # the already-computed analysis) and returns (caption, list[AIUsage]).
            service.ai_service.create_caption_from_analysis = AsyncMock(return_value=("fallback caption", []))  # type: ignore[method-assign, union-attr]

            result = await service.analyze_and_caption("test.jpg")

            assert result.caption == "fallback caption"
            assert result.sd_caption is None


class TestAnalyzeAndCaptionSidecarWriteException:
    """Tests for sidecar write exception handling (lines 337-339)."""

    @pytest.mark.asyncio
    async def test_continues_on_sidecar_write_failure(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """Verify analyze_and_caption continues when sidecar write fails."""
        monkeypatch.setenv("STORAGE_PATHS", '{"root": "/Photos", "archive": "archive"}')
        monkeypatch.setenv("PUBLISHERS", "[]")
        monkeypatch.setenv("OPENAI_SETTINGS", "{}")
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.core.models import ImageAnalysis
            from publisher_v2.web.service import WebImageService

            service = WebImageService()
            # #91 (SEC-11): filename ops validate against the image listing.
            service.storage.list_images = AsyncMock(return_value=["test.jpg", "nonexistent.jpg"])  # type: ignore[method-assign]
            service.storage.download_image = AsyncMock(return_value=b"image-bytes")  # type: ignore[method-assign]

            # Mock storage methods
            service.storage.get_temporary_link = AsyncMock(return_value="http://temp")  # type: ignore[method-assign]
            service.storage.download_sidecar_if_exists = AsyncMock(return_value=None)  # type: ignore[method-assign]

            # Mock AI service
            analysis = ImageAnalysis(
                description="Test",
                mood="neutral",
                tags=["test"],
                nsfw=False,
                safety_labels=[],
            )
            service.ai_service.analyzer.analyze = AsyncMock(return_value=(analysis, None))  # type: ignore[method-assign, union-attr]
            service.ai_service.create_caption_pair_from_analysis = AsyncMock(return_value=("caption", "sd_caption", []))  # type: ignore[method-assign, union-attr]
            ai = service.ai_service
            ai.create_multi_caption_pair_from_analysis = AsyncMock(  # type: ignore[method-assign, union-attr]
                return_value=({"generic": "caption"}, "sd_caption", [], {})  # PUB-051: + angles
            )
            # Keep a multi-path failure from reaching the real OpenAI client via the fallback.
            ai.create_caption_from_analysis = AsyncMock(  # type: ignore[method-assign, union-attr]
                side_effect=AssertionError("caption-only fallback ran; the multi-caption path failed")
            )

            # Mock sidecar generation to fail - the import is inside the method
            with patch("publisher_v2.services.sidecar.generate_and_upload_sidecar") as mock_sidecar:
                mock_sidecar.side_effect = Exception("Sidecar write failed")

                result = await service.analyze_and_caption("test.jpg")

                # Should still return valid response despite sidecar failure
                assert result.caption == "caption"
                assert result.sd_caption == "sd_caption"
                assert result.sidecar_written is False


class TestListImages:
    """Tests for list_images logic (lines 177-182)."""

    @pytest.mark.asyncio
    async def test_returns_sorted_list(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        """Verify list_images returns sorted filenames."""
        monkeypatch.setenv("STORAGE_PATHS", '{"root": "/Photos", "archive": "archive"}')
        monkeypatch.setenv("PUBLISHERS", "[]")
        monkeypatch.setenv("OPENAI_SETTINGS", "{}")
        monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
        monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
        monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

        with patch("publisher_v2.services.storage.dropbox.Dropbox"):
            from publisher_v2.web.service import WebImageService

            service = WebImageService()
            # #91 (SEC-11): filename ops validate against the image listing.
            service.storage.list_images = AsyncMock(return_value=["test.jpg", "nonexistent.jpg"])  # type: ignore[method-assign]
            service.storage.download_image = AsyncMock(return_value=b"image-bytes")  # type: ignore[method-assign]

            # Mock storage to return unsorted list
            service.storage.list_images = AsyncMock(return_value=["zebra.jpg", "apple.jpg", "mango.jpg"])  # type: ignore[method-assign]

            result = await service.list_images()

            assert result["filenames"] == ["apple.jpg", "mango.jpg", "zebra.jpg"]
            assert result["count"] == 3


# ---------------------------------------------------------------------------
# PUB-051 critique follow-up: the web Analyze path feeds the angle rotation and
# records the chosen angles in the sidecar, like the workflow does.
#
# Real AIService, CaptionStore (SQLite in memory) and WorkflowOrchestrator; only
# OpenAI (recording fake), storage and publishers are faked.
# ---------------------------------------------------------------------------


def _bare_web_service(config, storage, ai_service, caption_store, images: list[str], tenant: str = "t1"):
    """A WebImageService without __init__ (which loads env/config), wired to the given parts."""
    import logging

    from publisher_v2.config.runtime_settings import RuntimeSettings
    from publisher_v2.web.service import WebImageService

    svc = WebImageService.__new__(WebImageService)
    svc._settings = RuntimeSettings()
    svc.logger = logging.getLogger("test")
    svc._usage_meter = None
    svc._storage_ops_meter = None
    svc._caption_store = caption_store
    svc._publish_store = None
    svc._tenant = tenant
    svc._runtime = None
    svc._config_source = None
    svc._ai_unavailable_until = None
    svc.config = config
    svc.storage = storage
    svc.ai_service = ai_service
    svc._get_cached_images = AsyncMock(return_value=list(images))  # type: ignore[method-assign]
    return svc


def _spy_multi_caption(service) -> list[tuple[dict, tuple]]:
    """Record each create_multi_caption_pair_from_analysis call's kwargs and result, delegating to the real one."""
    calls: list[tuple[dict, tuple]] = []
    real = service.create_multi_caption_pair_from_analysis

    async def _spy(*args, **kwargs):
        result = await real(*args, **kwargs)
        calls.append((kwargs, result))
        return result

    service.create_multi_caption_pair_from_analysis = _spy
    return calls


async def _memory_session_factory():
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from publisher_v2.db.models import Base

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


@pytest.mark.asyncio
async def test_web_analyze_passes_stored_angles_to_the_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Web Analyze reads each platform's stored angles and hands them to the rotation as ``history_angles``."""
    from caption_pipeline_fakes import FakeOpenAI, SidecarStorage, install_fake_openai, pipeline_config, real_ai_service

    from publisher_v2.db.caption_store import CaptionStore
    from publisher_v2.utils.captions import CONTENT_ANGLES

    pool = list(CONTENT_ANGLES)
    engine, factory = await _memory_session_factory()
    try:
        store = CaptionStore(factory)
        # Oldest first: a legacy row with no angle, then two rows with stored angles.
        await store.save_captions_batch(tenant="t1", captions_by_platform={"telegram": "Legacy row, no angle."})
        await store.save_captions_batch(
            tenant="t1",
            captions_by_platform={"telegram": "Frayed ends and a bare wall."},
            angles_by_platform={"telegram": pool[3]},
        )
        await store.save_captions_batch(
            tenant="t1",
            captions_by_platform={"telegram": "Hemp, a kettle, the long second wrap."},
            angles_by_platform={"telegram": pool[1]},
        )

        fake = FakeOpenAI(["telegram"])
        install_fake_openai(monkeypatch, fake)
        ai = real_ai_service()
        calls = _spy_multi_caption(ai)
        svc = _bare_web_service(pipeline_config(telegram=True), SidecarStorage(["a.jpg"]), ai, store, ["a.jpg"])

        await svc.analyze_and_caption("a.jpg", force_refresh=True)

        assert len(calls) == 1, "web Analyze did not go through create_multi_caption_pair_from_analysis"
        kwargs, _result = calls[0]
        history_angles = kwargs.get("history_angles")
        assert history_angles, "web Analyze passed no history_angles to the rotation"
        stored = [a for a in history_angles.get("telegram", []) if a is not None]
        assert stored == [pool[1], pool[3]], f"expected the stored angles most-recent-first, got {history_angles}"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_web_analyze_survives_history_fetch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A caption-history read that raises does not break web Analyze: captions still come back,
    and the rotation gets no stored angles (``history_angles`` None or empty).
    """
    from caption_pipeline_fakes import FakeOpenAI, SidecarStorage, install_fake_openai, pipeline_config, real_ai_service

    from publisher_v2.db.caption_store import CaptionStore

    engine, factory = await _memory_session_factory()
    try:
        store = CaptionStore(factory)
        fetches: list[object] = []

        async def _boom(*args, **kwargs):
            fetches.append((args, kwargs))
            raise RuntimeError("database unavailable")

        monkeypatch.setattr(store, "fetch_recent_with_angles_by_platform", _boom)

        fake = FakeOpenAI(["telegram"])
        install_fake_openai(monkeypatch, fake)
        ai = real_ai_service()
        calls = _spy_multi_caption(ai)
        svc = _bare_web_service(pipeline_config(telegram=True), SidecarStorage(["a.jpg"]), ai, store, ["a.jpg"])

        response = await svc.analyze_and_caption("a.jpg", force_refresh=True)

        assert fetches, "setup: web Analyze never tried to read the caption history"
        assert response.caption, "web Analyze returned no caption after the history read failed"
        assert len(calls) == 1, "web Analyze fell off the multi-caption path after the history read failed"
        kwargs, result = calls[0]
        assert not kwargs.get("history_angles"), f"expected no history_angles, got {kwargs.get('history_angles')}"
        assert not kwargs.get("history"), f"expected no caption history, got {kwargs.get('history')}"
        assert result[0].get("telegram"), f"no telegram caption generated: {result[0]}"
    finally:
        await engine.dispose()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["workflow", "web"])
async def test_sidecar_records_caption_angles_next_to_caption_generated(
    path: str, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """The sidecar an analyze/caption stage writes carries ``caption_angles`` (platform -> angle key).

    It sits next to ``caption_generated`` and names the angle each generated
    caption was actually written under (the one the caption stage returned).
    """
    from caption_pipeline_fakes import (
        FakeOpenAI,
        ScriptedPublisher,
        SidecarStorage,
        install_fake_openai,
        pipeline_config,
        real_ai_service,
    )

    from publisher_v2.services.sidecar_parser import parse_sidecar_text
    from publisher_v2.utils.captions import CONTENT_ANGLES

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    platforms = ["telegram", "instagram"]
    fake = FakeOpenAI(platforms)
    install_fake_openai(monkeypatch, fake)
    ai = real_ai_service()
    calls = _spy_multi_caption(ai)
    storage = SidecarStorage(["a.jpg"])
    config = pipeline_config(telegram=True, instagram=True)

    if path == "workflow":
        from publisher_v2.core.workflow import WorkflowOrchestrator

        orchestrator = WorkflowOrchestrator(
            config, storage, ai, [ScriptedPublisher(p, [True]) for p in platforms], tenant="t1"
        )
        result = await orchestrator.execute(select_filename="a.jpg")
        assert result.success, result.error
    else:
        svc = _bare_web_service(config, storage, ai, None, ["a.jpg"])
        response = await svc.analyze_and_caption("a.jpg", force_refresh=True)
        assert response.sidecar_written is True

    assert len(calls) == 1
    returned_angles = calls[0][1][3]
    assert "a.jpg" in storage.sidecars, "no sidecar written"
    _sd, meta = parse_sidecar_text(storage.sidecars["a.jpg"])
    assert meta is not None
    assert isinstance(meta.get("caption_generated"), dict), "setup: caption_generated missing from the sidecar"
    recorded = meta.get("caption_angles")
    assert isinstance(recorded, dict), f"sidecar has no caption_angles map: {sorted(meta)}"
    assert set(recorded) == set(meta["caption_generated"]), (recorded, meta["caption_generated"])
    assert all(v in CONTENT_ANGLES for v in recorded.values()), recorded
    assert recorded == returned_angles, "caption_angles must be the angles the kept captions were written under"
