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


# --- #146: the FetLife subject limit is stated in three places; they must agree ---


from pathlib import Path  # noqa: E402

import yaml  # noqa: E402

STATIC = Path(__file__).resolve().parents[1] / "src" / "publisher_v2" / "config" / "static"


def _yaml(name: str) -> dict:
    with (STATIC / name).open() as fh:
        return yaml.safe_load(fh)


def test_the_three_email_limits_agree() -> None:
    from publisher_v2.utils.captions import _MAX_LEN

    platform_limit = _yaml("platform_limits.yaml")["email"]["max_caption_length"]
    prompt_limit = _yaml("ai_prompts.yaml")["platform_captions"]["email"]["max_length"]

    assert platform_limit == prompt_limit == _MAX_LEN["email"], (
        f"email limit disagrees: platform_limits.yaml={platform_limit}, "
        f"ai_prompts.yaml={prompt_limit}, captions._MAX_LEN={_MAX_LEN['email']}"
    )


def test_telegram_limits_agree_too() -> None:
    from publisher_v2.utils.captions import _MAX_LEN

    platform_limit = _yaml("platform_limits.yaml")["telegram"]["max_caption_length"]

    assert platform_limit == _MAX_LEN["telegram"]


def test_the_email_limit_change_requires_recorded_evidence() -> None:
    """The FetLife subject limit is an assumption from #79, not a measurement.

    #146 asks the account owner to send one email with a 264-character subject
    and record what FetLife displays. Changing the number without that evidence
    is how 240 got here in the first place.
    """
    assert _yaml("platform_limits.yaml")["email"]["max_caption_length"] == 240, (
        "the email limit changed: record the evidence (the subject length FetLife actually "
        "displayed, and when it was measured) in docs_v2/09_Reviews/fetlife_subject_limit.md "
        "and update this expectation in the same commit"
    )
