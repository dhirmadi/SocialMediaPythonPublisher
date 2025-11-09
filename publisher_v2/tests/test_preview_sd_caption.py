from __future__ import annotations

import io
import sys
import pytest

from publisher_v2.core.models import ImageAnalysis
from publisher_v2.utils.preview import print_vision_analysis


def test_preview_prints_sd_caption(monkeypatch: pytest.MonkeyPatch) -> None:
    analysis = ImageAnalysis(
        description="desc",
        mood="mood",
        tags=["a", "b"],
        nsfw=False,
        safety_labels=[],
        sd_caption="fine-art portrait, soft light",
    )
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    print_vision_analysis(analysis, model="gpt-4o")
    out = buf.getvalue()
    assert "SD Caption" in out

