from __future__ import annotations

import io
import sys
import pytest

from publisher_v2.utils.preview import (
    print_preview_header,
    print_image_details,
    print_platform_preview,
    print_email_confirmation_preview,
    print_config_summary,
    print_preview_footer,
    print_error,
)
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.core.models import PublishResult


class _PubBase(Publisher):
    def __init__(self, name: str, enabled: bool) -> None:
        self._name = name
        self._enabled = enabled

    @property
    def platform_name(self) -> str:
        return self._name

    def is_enabled(self) -> bool:
        return self._enabled

    async def publish(self, image_path: str, caption: str, context: dict | None = None) -> PublishResult:
        return PublishResult(success=True, platform=self.platform_name)


def _capture_output(fn, *args, **kwargs) -> str:
    buf = io.StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        fn(*args, **kwargs)
    finally:
        sys.stdout = old
    return buf.getvalue()


def test_preview_header_footer_and_error() -> None:
    assert "PREVIEW MODE" in _capture_output(print_preview_header)
    assert "NO ACTIONS TAKEN" in _capture_output(print_preview_footer)
    assert "ERROR" in _capture_output(print_error, "oops")


def test_image_details_status_branches() -> None:
    # already posted
    out = _capture_output(
        print_image_details,
        filename="a.jpg",
        folder="/path",
        sha256="1234567890abcdef1234567890abcdef",
        dropbox_url="http://x",
        is_new=False,
        already_posted=True,
    )
    assert "Previously posted" in out
    # new
    out2 = _capture_output(
        print_image_details,
        filename="b.jpg",
        folder="/path",
        sha256="abcdef1234567890abcdef1234567890",
        dropbox_url="http://x",
        is_new=True,
    )
    assert "New (not previously posted)" in out2
    # unknown
    out3 = _capture_output(
        print_image_details,
        filename="c.jpg",
        folder="/path",
        sha256="abcdef1234567890abcdef1234567890",
        dropbox_url="http://x",
        is_new=False,
    )
    assert "Unknown" in out3


def test_platform_preview_branches() -> None:
    pubs = [
        _PubBase("telegram", True),
        _PubBase("instagram", True),
        _PubBase("email", True),
        _PubBase("dummy", False),
    ]
    # Create a caption with >30 hashtags to trigger warning branch for Instagram
    many_hashtags = " ".join("#tag" + str(i) for i in range(40))
    platform_captions = {
        "telegram": "caption for tg",
        "instagram": many_hashtags,
        "email": "email caption",
    }
    out = _capture_output(
        print_platform_preview,
        publishers=pubs,
        caption="base caption",
        platform_captions=platform_captions,
        email_subject="subject line goes here",
        email_caption_target="subject",
        email_subject_mode="private",
    )
    assert "ENABLED" in out and "DISABLED" in out
    assert "1280px" in out  # telegram branch
    assert "1080px" in out  # instagram branch
    assert "Hashtags will be limited to 30" in out  # hashtag warning
    assert "Subject mode: private" in out  # email subject mode


def test_config_summary_prints() -> None:
    out = _capture_output(
        print_config_summary,
        vision_model="gpt-4o",
        caption_model="gpt-4o-mini",
        config_file="config.ini",
    )
    assert "Vision Model" in out and "Caption Model" in out and "config.ini" in out



