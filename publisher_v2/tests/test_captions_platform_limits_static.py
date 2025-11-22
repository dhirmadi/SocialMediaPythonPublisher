from __future__ import annotations

from publisher_v2.utils.captions import format_caption


def test_format_caption_uses_default_platform_limits_instagram() -> None:
    text = "caption " + " ".join(f"#tag{i}" for i in range(40))
    out = format_caption("instagram", text)
    # Default max length 2200, so caption should be unchanged in length semantics
    assert len(out) <= 2200
    # Default hashtag limit 30 – ensure we did not keep all 40
    assert out.count("#tag") <= 30


def test_format_caption_email_sanitizes_and_limits() -> None:
    text = "hello #tag1 #tag2 — “quoted”"
    out = format_caption("email", text)
    # Hashtags stripped and punctuation normalized
    assert "#" not in out
    assert " - " in out or "-" in out
    assert "“" not in out and "”" not in out


