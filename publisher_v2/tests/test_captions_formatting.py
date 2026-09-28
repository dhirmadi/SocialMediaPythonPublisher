from __future__ import annotations

import re

import pytest

from publisher_v2.config.static_loader import get_static_config
from publisher_v2.utils.captions import format_caption, smart_truncate


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


# --- PUB-084 AC15 (#281): one truncation algorithm, never over the platform limit ---------


def _platform_limit(platform: str) -> int:
    limits = get_static_config().platform_limits
    limit = getattr(limits, platform, limits.generic).max_caption_length
    assert limit, f"static config has no caption limit for {platform}"
    return int(limit)


def _pre_truncation(platform: str, text: str) -> str:
    """What ``format_caption`` feeds its truncation step, for the ASCII inputs below.

    The inputs hold at most a handful of hashtags and no punctuation FetLife rewrites, so
    Instagram's hashtag cap and the email sanitizer reduce to: strip, and (email only) drop
    every hashtag and collapse the gaps it leaves.
    """
    text = text.strip()
    if platform == "email":
        text = re.sub(r"\s{2,}", " ", re.sub(r"#\w+", "", text)).strip()
    return text


def _words(n_chars: int) -> str:
    """Space-separated words, no sentence end, at least ``n_chars`` long."""
    out = ""
    i = 0
    while len(out) < n_chars:
        out += f"word{i % 7}abc "
        i += 1
    return out.rstrip()


def _case(name: str, limit: int) -> str:
    if name == "short":
        return "A short caption. #rope #light"
    if name == "just_over":
        return _words(limit + 7)
    if name == "long_with_trailing_hashtags":
        return _words(limit - 10) + " #rope #shibari #light"
    if name == "single_long_word":
        return "x" * (limit + 50)
    if name == "sentence_end_at_limit":
        head = _words(limit - 1)[: limit - 1].rstrip()
        head = head + "a" * (limit - 1 - len(head))
        return head + ". And then the text keeps going past the limit"
    raise AssertionError(name)


_PLATFORMS = ["telegram", "instagram", "email", "generic", "mastodon"]
_CASES = ["short", "just_over", "long_with_trailing_hashtags", "single_long_word", "sentence_end_at_limit"]


@pytest.mark.parametrize("case", _CASES)
@pytest.mark.parametrize("platform", _PLATFORMS)
def test_format_caption_never_exceeds_platform_limit(platform: str, case: str) -> None:
    """AC15: the result fits the platform limit and is cut the way ``smart_truncate`` cuts.

    An unknown platform ("mastodon") uses the generic limit. The owner decision on #281:
    the hard limit wins over keeping trailing hashtags, and there is one truncation
    algorithm — ``smart_truncate`` at a sentence end, else a word boundary.
    """
    limit = _platform_limit(platform)
    caption = _case(case, limit)

    out = format_caption(platform, caption)

    assert len(out) <= limit, f"{platform}/{case}: {len(out)} > {limit}"
    # Wave 5: the FetLife (email) path cuts with an ASCII "..." - FetLife may strip "\u2026".
    ellipsis = "..." if platform == "email" else "\u2026"
    expected = smart_truncate(_pre_truncation(platform, caption), limit, ellipsis=ellipsis)
    assert out == expected, f"{platform}/{case}: got tail {out[-40:]!r}, smart_truncate gives {expected[-40:]!r}"


# --- PUB-084 wave 5 (#281): FetLife output never carries the unicode ellipsis ----------------


@pytest.mark.parametrize("case", ["just_over", "single_long_word"])
@pytest.mark.parametrize(("platform", "ellipsis"), [("email", "..."), ("telegram", "\u2026")])
def test_fetlife_truncation_uses_ascii_ellipsis(platform: str, ellipsis: str, case: str) -> None:
    """``_sanitize_for_fetlife`` rewrites "\u2026" to "..." because FetLife may strip it.

    Truncation runs after sanitising, so the email (FetLife) cut must append "..." itself.
    Telegram keeps the unicode ellipsis, which keeps the change scoped to the FetLife path.
    """
    limit = _platform_limit(platform)
    caption = _case(case, limit)

    out = format_caption(platform, caption)

    assert len(out) <= limit, f"{platform}/{case}: {len(out)} > {limit}"
    assert out.endswith(ellipsis), f"{platform}/{case}: got tail {out[-20:]!r}"
    if platform == "email":
        assert "\u2026" not in out, f"email/{case}: unicode ellipsis in {out[-20:]!r}"


# --- PUB-084 wave 5 (#281): pin the emoji class before the regexes are shared ------------

# The two emoji classes differ today: ``utils.captions`` also matches the variation selectors
# U+FE00-U+FE0F and the zero-width joiner U+200D; ``utils.caption_metrics`` does not (it only
# lets variation selectors ride along in a trailing run). These inputs sit in that difference.
EMOJI_CLASS_INPUTS = [
    "Rope. Light. \U0001f525",  # ordinary emoji
    "Rope. Light. ❤️",  # heart + variation selector
    "Rope. Light. ️",  # a lone variation selector
    "Rope. Light. ‍",  # a lone zero-width joiner
    "Rope. Light. \U0001f469‍\U0001f525",  # ZWJ sequence
    "Rope. Light.",  # no emoji
    "Window️ light‍ here #tag → end",  # selector/ZWJ mid-text, hashtag, arrow
]


@pytest.mark.parametrize(
    ("text", "expected"),
    list(
        zip(
            EMOJI_CLASS_INPUTS,
            [
                "Rope. Light.",
                "Rope. Light.",
                "Rope. Light.",
                "Rope. Light.",
                "Rope. Light.",
                "Rope. Light.",
                "Window light here end",
            ],
            strict=True,
        )
    ),
)
def test_strip_emoji_and_hashtags_pins_current_emoji_class(text: str, expected: str) -> None:
    """Refactor guard, captured 2026-09-28: selectors, ZWJ and arrows are all stripped."""
    from publisher_v2.utils.captions import strip_emoji_and_hashtags

    assert strip_emoji_and_hashtags(text) == expected
