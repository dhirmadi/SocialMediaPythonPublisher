"""Tests for preview mode displaying per-platform captions (AC18)."""

from __future__ import annotations

from publisher_v2.core.models import WorkflowResult


class TestPreviewPlatformCaptions:
    """AC18: Preview mode displays all per-platform AI-generated captions."""

    def test_workflow_result_has_platform_captions(self) -> None:
        result = WorkflowResult(
            success=True,
            image_name="test.jpg",
            caption="primary caption",
            publish_results={},
            archived=False,
            platform_captions={"telegram": "tg cap", "email": "email cap"},
        )
        assert result.platform_captions["telegram"] == "tg cap"
        assert result.platform_captions["email"] == "email cap"

    def test_workflow_result_platform_captions_default_empty(self) -> None:
        result = WorkflowResult(
            success=True,
            image_name="test.jpg",
            caption="primary",
            publish_results={},
            archived=False,
        )
        assert result.platform_captions == {}
