"""Tests for multi-caption workflow integration (AC9-12)."""

from __future__ import annotations

import pytest
from conftest import BaseDummyAI, BaseDummyPublisher, BaseDummyStorage

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    EmailConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
)
from publisher_v2.core.models import CaptionSpec, ImageAnalysis
from publisher_v2.core.workflow import WorkflowOrchestrator


def _make_config(
    telegram: bool = False,
    instagram: bool = False,
    email: bool = False,
) -> ApplicationConfig:
    return ApplicationConfig(
        dropbox=DropboxConfig(app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos"),
        storage_paths=StoragePathConfig(image_folder="/Photos"),
        openai=OpenAIConfig(
            api_key="sk-test",
            sd_caption_enabled=False,
            sd_caption_single_call_enabled=False,
        ),
        platforms=PlatformsConfig(telegram_enabled=telegram, instagram_enabled=instagram, email_enabled=email),
        telegram=None,
        instagram=None,
        email=EmailConfig(
            smtp_server="smtp.test",
            smtp_port=587,
            sender="f@t",
            recipient="t@t",
            password="p",
        )
        if email
        else None,
        content=ContentConfig(hashtag_string="#test", archive=False, debug=False),
    )


class MultiCaptionAI(BaseDummyAI):
    """AI service that supports multi-platform caption generation."""

    def __init__(self, platform_captions: dict[str, str] | None = None) -> None:
        super().__init__()
        self._platform_captions = platform_captions or {}

    async def create_multi_caption_pair_from_analysis(
        self, analysis: ImageAnalysis, specs: dict[str, CaptionSpec]
    ) -> tuple[dict[str, str], str | None, list]:
        if self._platform_captions:
            return self._platform_captions, None, []
        return {k: f"{k}-generated-caption" for k in specs}, None, []


class TestEachPublisherReceivesOwnCaption:
    """AC9: Each publisher receives its platform-specific caption."""

    @pytest.mark.asyncio
    async def test_each_publisher_receives_own_caption(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: set())
        monkeypatch.setattr("publisher_v2.core.workflow.save_posted_hash", lambda h: None)
        monkeypatch.setattr("publisher_v2.core.workflow.load_posted_content_hashes", lambda: set())
        monkeypatch.setattr("publisher_v2.core.workflow.save_posted_content_hash", lambda h: None)

        cfg = _make_config(telegram=True, email=True)
        storage = BaseDummyStorage()

        tg_pub = BaseDummyPublisher(platform="telegram")
        email_pub = BaseDummyPublisher(platform="email")

        ai = MultiCaptionAI(
            platform_captions={
                "telegram": "Telegram-specific caption",
                "email": "Email-specific caption",
            }
        )

        pubs: list = [tg_pub, email_pub]
        orch = WorkflowOrchestrator(cfg, storage, ai, pubs)  # type: ignore[arg-type]
        result = await orch.execute(select_filename="test.jpg")

        assert result.success
        # Each publisher should have received its own caption
        assert len(tg_pub.publish_calls) == 1
        assert len(email_pub.publish_calls) == 1
        # The captions should contain the platform-specific content
        # (format_caption may modify them, but the base should be platform-specific)
        tg_caption = tg_pub.publish_calls[0][1]
        email_caption = email_pub.publish_calls[0][1]
        assert "Telegram-specific" in tg_caption
        assert tg_caption != email_caption

    @pytest.mark.asyncio
    async def test_platform_captions_in_result(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """WorkflowResult.platform_captions carries the full dict."""
        monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: set())
        monkeypatch.setattr("publisher_v2.core.workflow.save_posted_hash", lambda h: None)
        monkeypatch.setattr("publisher_v2.core.workflow.load_posted_content_hashes", lambda: set())
        monkeypatch.setattr("publisher_v2.core.workflow.save_posted_content_hash", lambda h: None)

        cfg = _make_config(telegram=True, instagram=True)
        storage = BaseDummyStorage()
        ai = MultiCaptionAI()
        pubs: list = [BaseDummyPublisher(platform="telegram"), BaseDummyPublisher(platform="instagram")]
        orch = WorkflowOrchestrator(cfg, storage, ai, pubs)  # type: ignore[arg-type]
        result = await orch.execute(select_filename="test.jpg")

        assert "telegram" in result.platform_captions
        assert "instagram" in result.platform_captions


class TestFormatCaptionSafetyNet:
    """AC10: format_caption still applies as safety net after AI generation."""

    @pytest.mark.asyncio
    async def test_format_caption_still_applied_as_safety_net(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: set())
        monkeypatch.setattr("publisher_v2.core.workflow.save_posted_hash", lambda h: None)
        monkeypatch.setattr("publisher_v2.core.workflow.load_posted_content_hashes", lambda: set())
        monkeypatch.setattr("publisher_v2.core.workflow.save_posted_content_hash", lambda h: None)

        cfg = _make_config(email=True)
        storage = BaseDummyStorage()
        # Give email a caption with hashtags — format_caption for email should strip them
        ai = MultiCaptionAI(platform_captions={"email": "Caption with #hashtag"})
        pub = BaseDummyPublisher(platform="email")
        pubs: list = [pub]
        orch = WorkflowOrchestrator(cfg, storage, ai, pubs)  # type: ignore[arg-type]
        await orch.execute(select_filename="test.jpg")

        # format_caption for email strips hashtags
        email_caption = pub.publish_calls[0][1]
        assert "#hashtag" not in email_caption


class TestCaptionOverride:
    """AC11: caption_override applies to all publishers."""

    @pytest.mark.asyncio
    async def test_caption_override_applies_to_all_publishers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: set())
        monkeypatch.setattr("publisher_v2.core.workflow.save_posted_hash", lambda h: None)
        monkeypatch.setattr("publisher_v2.core.workflow.load_posted_content_hashes", lambda: set())
        monkeypatch.setattr("publisher_v2.core.workflow.save_posted_content_hash", lambda h: None)

        cfg = _make_config(telegram=True, email=True)
        storage = BaseDummyStorage()
        ai = MultiCaptionAI()
        tg_pub = BaseDummyPublisher(platform="telegram")
        email_pub = BaseDummyPublisher(platform="email")

        pubs: list = [tg_pub, email_pub]
        orch = WorkflowOrchestrator(cfg, storage, ai, pubs)  # type: ignore[arg-type]
        result = await orch.execute(select_filename="test.jpg", caption_override="Manual override text")

        # Both publishers should have received the override (after format_caption)
        tg_caption = tg_pub.publish_calls[0][1]
        assert "Manual override" in tg_caption
        # Caption override bypasses multi-generation
        assert result.platform_captions == {}


class TestSinglePublisher:
    """AC12: Single publisher behaves equivalently to current behavior."""

    @pytest.mark.asyncio
    async def test_single_publisher_generates_single_caption(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("publisher_v2.core.workflow.load_posted_hashes", lambda: set())
        monkeypatch.setattr("publisher_v2.core.workflow.save_posted_hash", lambda h: None)
        monkeypatch.setattr("publisher_v2.core.workflow.load_posted_content_hashes", lambda: set())
        monkeypatch.setattr("publisher_v2.core.workflow.save_posted_content_hash", lambda h: None)

        cfg = _make_config(telegram=True)
        storage = BaseDummyStorage()
        ai = MultiCaptionAI()
        pub = BaseDummyPublisher(platform="telegram")
        pubs: list = [pub]
        orch = WorkflowOrchestrator(cfg, storage, ai, pubs)  # type: ignore[arg-type]
        result = await orch.execute(select_filename="test.jpg")

        assert result.success
        assert len(pub.publish_calls) == 1
        # Should have generated at least one caption
        assert result.caption
