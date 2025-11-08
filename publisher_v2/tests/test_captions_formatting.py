from __future__ import annotations

from publisher_v2.utils.captions import format_caption


def test_instagram_hashtag_limit_and_length():
    base = "A" * 2100 + " " + " ".join(f"#tag{i}" for i in range(40))
    out = format_caption("instagram", base)
    # Should not exceed 2200 chars
    assert len(out) <= 2200
    # Should limit to <= 30 hashtags
    num_tags = out.count("#")
    assert num_tags <= 30


def test_telegram_long_caption_allowed():
    base = "B" * 5000
    out = format_caption("telegram", base)
    assert len(out) <= 4096


