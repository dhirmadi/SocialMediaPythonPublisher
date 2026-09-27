"""CAP-2 (#80): web analyze must never serve the SD prompt as the caption.

Sidecar with only an SD line → run the AI path. Sidecar carrying
caption_generated → serve the cached social caption with cached=True.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, patch


class TestAnalyzeSidecarCache:
    async def test_sd_only_sidecar_runs_ai_and_never_returns_sd_prompt(
        self, analyze_service: Callable[..., Any]
    ) -> None:
        sidecar = "the stable diffusion prompt\n\n# ---\n# image_file: img.jpg\n"
        service = analyze_service(sidecar=sidecar)

        with patch("publisher_v2.services.sidecar.generate_and_upload_sidecar", new=AsyncMock(return_value=1.0)):
            result = await service.analyze_and_caption("img.jpg")

        assert result.caption == "fresh AI caption"
        assert result.caption != "the stable diffusion prompt"
        assert result.cached is False
        service.ai_service.analyzer.analyze.assert_awaited_once()  # type: ignore[union-attr]

    async def test_caption_generated_sidecar_served_from_cache(self, analyze_service: Callable[..., Any]) -> None:
        sidecar = 'sd prompt\n\n# ---\n# caption_generated: {"email": "Email cap?"}\n'
        service = analyze_service(sidecar=sidecar)

        result = await service.analyze_and_caption("img.jpg")

        assert result.caption == "Email cap?"
        assert result.cached is True
        service.ai_service.analyzer.analyze.assert_not_awaited()  # type: ignore[union-attr]

    async def test_published_caption_metadata_still_served(self, analyze_service: Callable[..., Any]) -> None:
        sidecar = "sd prompt\n\n# ---\n# caption: The published caption\n"
        service = analyze_service(sidecar=sidecar)

        result = await service.analyze_and_caption("img.jpg")

        assert result.caption == "The published caption"
        assert result.cached is True

    async def test_force_refresh_bypasses_cache(self, analyze_service: Callable[..., Any]) -> None:
        sidecar = 'sd prompt\n\n# ---\n# caption_generated: {"email": "Email cap?"}\n'
        service = analyze_service(sidecar=sidecar)

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
        self, analyze_service: Callable[..., Any]
    ) -> None:
        """No enabled-platform or email entry — any generated caption beats re-running AI."""
        sidecar = 'sd prompt\n\n# ---\n# caption_generated: {"instagram": "IG cap"}\n'
        service = analyze_service(sidecar=sidecar)

        result = await service.analyze_and_caption("img.jpg")

        assert result.caption == "IG cap"
        assert result.cached is True
