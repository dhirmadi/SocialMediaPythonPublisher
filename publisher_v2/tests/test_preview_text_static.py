from __future__ import annotations

import io
import sys

from publisher_v2.utils.preview import print_preview_header, print_preview_footer


def test_preview_header_uses_default_static_text(monkeypatch) -> None:
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    print_preview_header()
    out = buf.getvalue()
    assert "PUBLISHER V2 - PREVIEW MODE" in out


def test_preview_footer_uses_default_static_text(monkeypatch) -> None:
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    print_preview_footer()
    out = buf.getvalue()
    assert "PREVIEW MODE - NO ACTIONS TAKEN" in out


