"""CAP-2 (#80): web analyze must never serve the SD prompt as the caption.

Sidecar with only an SD line → run the AI path. Sidecar carrying
caption_generated → serve the cached social caption with cached=True.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from publisher_v2.core.models import ImageAnalysis

VALID_INI_CONTENT = """
[Dropbox]
image_folder = /Photos
archive_folder = archive

[OpenAI]

[Content]
hashtag_string = #test
archive = false
debug = false

[Features]
analyze_caption_enabled = true
publish_enabled = true

[Platforms]
telegram_enabled = false
instagram_enabled = false
email_enabled = false
"""


def _make_service(monkeypatch: pytest.MonkeyPatch, tmp_path, sidecar_text: str | None):
    config_file = tmp_path / "test.ini"
    config_file.write_text(VALID_INI_CONTENT)
    monkeypatch.setenv("CONFIG_PATH", str(config_file))
    monkeypatch.setenv("DROPBOX_APP_KEY", "test_key")
    monkeypatch.setenv("DROPBOX_APP_SECRET", "test_secret")
    monkeypatch.setenv("DROPBOX_REFRESH_TOKEN", "test_refresh")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    with patch("publisher_v2.services.storage.dropbox.Dropbox"):
        from publisher_v2.web.service import WebImageService

        service = WebImageService()

    service.storage.get_temporary_link = AsyncMock(return_value="http://temp")  # type: ignore[method-assign]
    blob = sidecar_text.encode() if sidecar_text is not None else None
    service.storage.download_sidecar_if_exists = AsyncMock(return_value=blob)  # type: ignore[method-assign]

    analysis = ImageAnalysis(description="Test", mood="neutral", tags=["t"], nsfw=False, safety_labels=[])
    service.ai_service.analyzer.analyze = AsyncMock(return_value=(analysis, None))  # type: ignore[method-assign, union-attr]
    service.ai_service.create_multi_caption_pair_from_analysis = AsyncMock(  # type: ignore[method-assign, union-attr]
        return_value=({"generic": "fresh AI caption"}, "fresh sd", [])
    )
    return service


class TestAnalyzeSidecarCache:
    async def test_sd_only_sidecar_runs_ai_and_never_returns_sd_prompt(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        sidecar = "the stable diffusion prompt\n\n# ---\n# image_file: img.jpg\n"
        service = _make_service(monkeypatch, tmp_path, sidecar)

        with patch("publisher_v2.services.sidecar.generate_and_upload_sidecar", new=AsyncMock(return_value=1.0)):
            result = await service.analyze_and_caption("img.jpg")

        assert result.caption == "fresh AI caption"
        assert result.caption != "the stable diffusion prompt"
        assert result.cached is False
        service.ai_service.analyzer.analyze.assert_awaited_once()  # type: ignore[union-attr]

    async def test_caption_generated_sidecar_served_from_cache(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        sidecar = 'sd prompt\n\n# ---\n# caption_generated: {"email": "Email cap?"}\n'
        service = _make_service(monkeypatch, tmp_path, sidecar)

        result = await service.analyze_and_caption("img.jpg")

        assert result.caption == "Email cap?"
        assert result.cached is True
        service.ai_service.analyzer.analyze.assert_not_awaited()  # type: ignore[union-attr]

    async def test_published_caption_metadata_still_served(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        sidecar = "sd prompt\n\n# ---\n# caption: The published caption\n"
        service = _make_service(monkeypatch, tmp_path, sidecar)

        result = await service.analyze_and_caption("img.jpg")

        assert result.caption == "The published caption"
        assert result.cached is True

    async def test_force_refresh_bypasses_cache(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        sidecar = 'sd prompt\n\n# ---\n# caption_generated: {"email": "Email cap?"}\n'
        service = _make_service(monkeypatch, tmp_path, sidecar)

        with patch("publisher_v2.services.sidecar.generate_and_upload_sidecar", new=AsyncMock(return_value=1.0)):
            result = await service.analyze_and_caption("img.jpg", force_refresh=True)

        assert result.caption == "fresh AI caption"
        assert result.cached is False


def test_analysis_response_cached_defaults_false() -> None:
    from publisher_v2.web.models import AnalysisResponse

    resp = AnalysisResponse(filename="a.jpg", description="", mood="", tags=[], nsfw=False, caption="", sd_caption=None)
    assert resp.cached is False


class TestCachedCaptionSelectionFallback:
    async def test_generated_entry_for_non_enabled_platform_still_served(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        """No enabled-platform or email entry — any generated caption beats re-running AI."""
        sidecar = 'sd prompt\n\n# ---\n# caption_generated: {"instagram": "IG cap"}\n'
        service = _make_service(monkeypatch, tmp_path, sidecar)

        result = await service.analyze_and_caption("img.jpg")

        assert result.caption == "IG cap"
        assert result.cached is True
