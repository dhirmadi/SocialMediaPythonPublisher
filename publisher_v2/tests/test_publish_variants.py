"""REL-1 (#83): per-platform image variants rendered once by the orchestrator.

Publishers must never write to a path they did not create; Telegram gets the
1280-wide variant, Instagram 1080, email the untouched original.
"""

from __future__ import annotations

from io import BytesIO
from typing import Any

from caption_pipeline_fakes import BaseDummyStorage, make_app_config, stub_ai_service
from PIL import Image

from publisher_v2.core.models import PublishResult
from publisher_v2.core.workflow import WorkflowOrchestrator
from publisher_v2.services.publishers.base import Publisher


def _png_bytes(width: int = 2000, height: int = 1000) -> bytes:
    buf = BytesIO()
    with Image.new("RGB", (width, height), color="red") as img:
        img.save(buf, format="PNG")
    return buf.getvalue()


class _RecordingPublisher(Publisher):
    """Records the path and bytes it was handed at publish time."""

    def __init__(self, name: str, received: dict[str, dict[str, Any]]) -> None:
        self._name = name
        self._received = received

    @property
    def platform_name(self) -> str:
        return self._name

    def is_enabled(self) -> bool:
        return True

    async def publish(self, image_path: str, caption: str, context: Any = None) -> PublishResult:
        with open(image_path, "rb") as f:  # noqa: ASYNC230 — test helper reads a tiny local file
            data = f.read()
        with Image.open(BytesIO(data)) as img:
            width = img.size[0]
        self._received[self._name] = {"path": image_path, "bytes": data, "width": width}
        return PublishResult(success=True, platform=self._name)


async def test_each_publisher_gets_its_own_variant() -> None:
    source = _png_bytes(2000, 1000)
    storage = BaseDummyStorage(images=["test.jpg"], content=source)
    received: dict[str, dict[str, Any]] = {}
    publishers: list[Publisher] = [
        _RecordingPublisher("telegram", received),
        _RecordingPublisher("instagram", received),
        _RecordingPublisher("email", received),
    ]

    orchestrator = WorkflowOrchestrator(make_app_config(), storage, stub_ai_service(), publishers)
    result = await orchestrator.execute()

    assert result.success, result.error
    assert received["telegram"]["width"] == 1280
    assert received["instagram"]["width"] == 1080
    # Email has no resize_width_px — it must receive the original bytes.
    assert received["email"]["bytes"] == source
    # Three distinct paths: no publisher shares a mutated file with another.
    paths = {info["path"] for info in received.values()}
    assert len(paths) == 3


async def test_source_temp_file_unchanged_and_variants_cleaned_up() -> None:
    source = _png_bytes(2000, 1000)
    storage = BaseDummyStorage(images=["test.jpg"], content=source)
    received: dict[str, dict[str, Any]] = {}
    publishers: list[Publisher] = [
        _RecordingPublisher("telegram", received),
        _RecordingPublisher("email", received),
    ]

    orchestrator = WorkflowOrchestrator(make_app_config(), storage, stub_ai_service(), publishers)
    result = await orchestrator.execute()

    assert result.success, result.error
    # The email publisher read the source path — bytes must be the original.
    assert received["email"]["bytes"] == source
    # All temp files (source + variants) are removed after the run.
    import os

    for info in received.values():
        assert not os.path.exists(info["path"])  # noqa: ASYNC240 — test assertion
