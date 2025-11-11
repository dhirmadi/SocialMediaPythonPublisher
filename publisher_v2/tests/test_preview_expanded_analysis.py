from __future__ import annotations

import io
import sys
import pytest

from publisher_v2.core.models import ImageAnalysis
from publisher_v2.utils.preview import print_vision_analysis


def _make_analysis() -> ImageAnalysis:
    return ImageAnalysis(
        description="A dramatic portrait in soft light.",
        mood="dramatic",
        tags=["portrait", "softlight"],
        nsfw=False,
        safety_labels=[],
        subject="single subject, torso",
        style="fine-art",
        lighting="soft directional",
        camera="50mm",
        clothing_or_accessories="rope harness",
        aesthetic_terms=["minimalist", "graphic"],
        pose="upright",
        composition="center-weighted",
        background="plain backdrop",
        color_palette="black and white",
    )


def test_preview_prints_optional_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    analysis = _make_analysis()
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    print_vision_analysis(analysis, model="gpt-4o")
    out = buf.getvalue()
    # Check key optional fields appear
    assert "Subject" in out
    assert "Style" in out
    assert "Lighting" in out
    assert "Camera" in out
    assert "Clothing" in out
    assert "Aesthetics" in out
    assert "Pose" in out
    assert "Composition" in out
    assert "Background" in out
    assert "Palette" in out



