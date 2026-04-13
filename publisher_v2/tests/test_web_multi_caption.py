"""Tests for web AnalysisResponse platform_captions field (AC19)."""

from __future__ import annotations

from publisher_v2.web.models import AnalysisResponse


class TestAnalysisResponsePlatformCaptions:
    """AC19: AnalysisResponse gains platform_captions field."""

    def test_analysis_response_includes_platform_captions(self) -> None:
        resp = AnalysisResponse(
            filename="test.jpg",
            description="desc",
            mood="calm",
            tags=["tag"],
            nsfw=False,
            caption="primary caption",
            sd_caption=None,
            sidecar_written=False,
            platform_captions={"telegram": "tg", "instagram": "ig"},
        )
        assert resp.platform_captions == {"telegram": "tg", "instagram": "ig"}
        assert resp.caption == "primary caption"

    def test_analysis_response_platform_captions_default_none(self) -> None:
        resp = AnalysisResponse(
            filename="test.jpg",
            description="",
            mood="",
            tags=[],
            nsfw=False,
            caption="",
            sidecar_written=False,
        )
        assert resp.platform_captions is None
