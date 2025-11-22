from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pytest
from PIL import Image

from publisher_v2.core.models import CaptionSpec, ImageAnalysis
from publisher_v2.services.publishers.base import Publisher
from publisher_v2.utils import images, logging as utils_logging, preview, state


class _StubPublisher(Publisher):
    def __init__(self, name: str, enabled: bool) -> None:
        self._name = name
        self._enabled = enabled

    @property
    def platform_name(self) -> str:
        return self._name

    def is_enabled(self) -> bool:
        return self._enabled

    async def publish(self, image_path: str, caption: str, context: dict | None = None):
        raise NotImplementedError


@pytest.fixture(autouse=True)
def _reset_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))


@pytest.mark.asyncio
async def test_image_resize_helpers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    image_path = tmp_path / "sample.jpg"
    with Image.new("RGB", (2000, 1000), color="red") as img:
        img.save(image_path)

    resized_path = images.ensure_max_width(str(image_path), max_width=1000)
    assert resized_path == str(image_path)
    with Image.open(resized_path) as updated:
        assert updated.size[0] == 1000

    async def fake_to_thread(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr("publisher_v2.utils.images.asyncio.to_thread", fake_to_thread)
    out = await images.ensure_max_width_async(str(image_path), max_width=800)
    assert out == str(image_path)


def test_logging_helpers(monkeypatch: pytest.MonkeyPatch) -> None:
    token_text = "sk-abcdefghijklmnopqrstuvwxyz123456 r8_token 123456:ABCDEFGHIJKLMNOPQRSTUV"
    sanitized = utils_logging.sanitize(token_text)
    assert "[OPENAI_KEY_REDACTED]" in sanitized
    assert "[REPLICATE_TOKEN_REDACTED]" in sanitized
    assert "[TELEGRAM_TOKEN_REDACTED]" in sanitized

    handler = logging.Handler()
    handler.emit = lambda record: None  # type: ignore[assignment]
    root = logging.getLogger()
    root.addHandler(handler)
    utils_logging.setup_logging(logging.DEBUG)
    assert root.handlers and isinstance(root.handlers[0], logging.Handler)

    class _CaptureHandler(logging.Handler):
        def __init__(self) -> None:
            super().__init__()
            self.messages: list[str] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.messages.append(record.getMessage())

    handler = _CaptureHandler()
    logger = logging.getLogger("publisher_v2.tests.logging")
    logger.handlers = []
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    utils_logging.log_json(logger, logging.INFO, "publisher_publish", token=token_text)
    assert handler.messages
    entry = json.loads(handler.messages[-1])
    assert entry["message"] == "publisher_publish"
    assert entry["token"] == token_text

    monkeypatch.setattr("publisher_v2.utils.logging.elapsed_ms", lambda start: 42)
    utils_logging.log_publisher_publish(logger, "email", utils_logging.now_monotonic(), success=True)
    final_entry = json.loads(handler.messages[-1])
    assert final_entry["platform"] == "email"

    start = utils_logging.now_monotonic()
    assert isinstance(start, float)
    assert isinstance(utils_logging.elapsed_ms(start), int)


def test_state_helpers_handle_formats(tmp_path: Path) -> None:
    cache_dir = Path(tmp_path) / "publisher_v2"
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "posted.json"

    cache_file.write_text(json.dumps(["legacy"]))
    assert state.load_posted_hashes() == {"legacy"}

    cache_file.write_text(json.dumps({"hashes": ["one"], "dropbox_content_hashes": ["db1"]}))
    assert state.load_posted_hashes() == {"one"}
    assert state.load_posted_content_hashes() == {"db1"}

    state.save_posted_hash("two")
    state.save_posted_hash("two")
    assert state.load_posted_hashes() == {"one", "two"}

    state.save_posted_content_hash("db2")
    state.save_posted_content_hash("")
    assert state.load_posted_content_hashes() == {"db1", "db2"}


def test_state_handles_missing_and_corrupt_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cache_dir = Path(tmp_path) / "publisher_v2"
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    # Missing file path
    assert state.load_posted_hashes() == set()

    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / "posted.json"
    cache_file.write_text("")
    assert state.load_posted_content_hashes() == set()

    cache_file.write_text("not json")
    assert state.load_posted_hashes() == set()


def test_preview_helpers_cover_branches(capfd: pytest.CaptureFixture[str]) -> None:
    analysis = ImageAnalysis(
        description="A long poetic description that should wrap a little bit for display.",
        mood="Serene",
        tags=["sunset", "mountain", "sky"],
        nsfw=False,
        safety_labels=["safe"],
        sd_caption="intricate portrait of a traveler",
        subject="traveler",
        style="film",
        lighting="golden hour",
        camera="mirrorless",
        clothing_or_accessories="linen coat",
        aesthetic_terms=["moody", "ambient"],
        pose="contemplative",
        composition="rule of thirds",
        background="sunlit cliffs",
        color_palette="warm hues",
    )
    spec = CaptionSpec(platform="instagram", style="poetic", hashtags="#one #two", max_length=2200)
    pubs = [
        _StubPublisher("telegram", True),
        _StubPublisher("instagram", True),
        _StubPublisher("email", True),
        _StubPublisher("fetlife", False),
    ]

    preview.print_preview_header()
    preview.print_image_details(
        filename="image.jpg",
        folder="/Photos",
        sha256="1" * 64,
        dropbox_url="https://dropbox",
        is_new=True,
        already_posted=False,
    )
    preview.print_vision_analysis(None, "gpt-4o", feature_enabled=False)
    preview.print_vision_analysis(analysis, "gpt-4o")
    preview.print_caption("", spec, "gpt-4o-mini", 0, feature_enabled=False)
    preview.print_caption("short caption text", spec, "gpt-4o-mini", 2)
    preview.print_platform_preview(
        pubs,
        caption="Default caption for all",
        platform_captions={"instagram": "Caption with #hashtags " + "#tag" * 40},
        email_subject="Subject line for email",
        email_caption_target="both",
        email_subject_mode="private",
        publish_enabled=True,
    )
    preview.print_email_confirmation_preview(True, True, 2, ["a", "b", "c"], "short tags")
    preview.print_config_summary("gpt-4o", "gpt-4o-mini", "config.ini")
    preview.print_error("Something went wrong")
    preview.print_caption_sidecar_preview("sd caption", {"image_file": "image.jpg"})
    preview.print_curation_action("image.jpg", "/Photos", "keep", "keep")
    preview.print_preview_footer()
    assert preview._wrap_text("short", 60) == ["short"]
    assert preview._count_hashtags("#one #two") == 2

    out = capfd.readouterr().out
    assert "PREVIEW MODE" in out
    assert "CURATION ACTION" in out
    assert "EMAIL CONFIRMATION" in out

