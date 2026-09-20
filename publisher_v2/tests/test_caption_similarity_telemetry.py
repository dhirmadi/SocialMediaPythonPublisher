"""#144 item 2: caption similarity telemetry is emitted on every run."""

from __future__ import annotations

import logging
from typing import Any

import pytest

from publisher_v2.core.models import ImageAnalysis


def _analysis() -> ImageAnalysis:
    return ImageAnalysis(description="d", mood="m", tags=["t"], nsfw=False, safety_labels=[])


class _Generator:
    model = "gpt-test"

    async def generate_multi(self, analysis: Any, specs: Any, **kwargs: Any) -> tuple[dict[str, str], None]:
        return ({"telegram": "a caption"}, None), None  # type: ignore[return-value]


@pytest.fixture
def service() -> Any:
    from publisher_v2.services.ai import AIService

    svc = AIService.__new__(AIService)

    class _NoopLimiter:
        async def __aenter__(self) -> None:
            return None

        async def __aexit__(self, *exc: object) -> bool:
            return False

    svc._rate_limiter = _NoopLimiter()  # type: ignore[attr-defined]
    return svc


class TestSimilarityTelemetryAlwaysEmitted:
    """#144 item 2: dashboards need a value on every run, not only when history is a non-empty dict."""

    async def test_empty_history_still_logs_the_event(self, service: Any, caplog: pytest.LogCaptureFixture) -> None:
        caplog.set_level(logging.INFO, logger="publisher_v2.services.ai")

        async def _generate_once(_clause: str | None) -> tuple[dict[str, str], str | None]:
            return {"telegram": "a caption"}, None

        captions, _sd = await service._apply_similarity_gate({"telegram": "a caption"}, None, {}, _generate_once)

        assert captions == {"telegram": "a caption"}
        events = [r.getMessage() for r in caplog.records if "caption_similarity" in r.getMessage()]
        assert events, caplog.text
        assert '"max_similarity": 0.0' in events[0]
        assert '"history_size": 0' in events[0]

    async def test_history_size_reflects_the_platform_history(
        self, service: Any, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.INFO, logger="publisher_v2.services.ai")

        async def _generate_once(_clause: str | None) -> tuple[dict[str, str], str | None]:
            return {"telegram": "fresh"}, None

        await service._apply_similarity_gate(
            {"telegram": "totally different words here"},
            None,
            {"telegram": ["one past caption", "another past caption"]},
            _generate_once,
        )

        events = [r.getMessage() for r in caplog.records if "caption_similarity" in r.getMessage()]
        assert events, caplog.text
        assert '"history_size": 2' in events[0]


class _MultiGenerator:
    """Generator double for the real caller: no SD path, records the calls it gets."""

    model = "gpt-test"
    sd_caption_enabled = False

    def __init__(self) -> None:
        self.calls: list[Any] = []

    async def generate_multi(self, analysis: Any, specs: Any, **kwargs: Any) -> tuple[dict[str, str], None]:
        self.calls.append(kwargs.get("diversity_clause"))
        return {"telegram": "a caption"}, None


def _spec() -> Any:
    from publisher_v2.core.models import CaptionSpec

    return CaptionSpec(platform="telegram", style="s", hashtags="", max_length=100)


class TestTelemetryReachesTheGateFromTheRealCaller:
    """#144 item 2: the fix removed an ``if history_dict:`` short-circuit in
    ``create_multi_caption_pair_from_analysis``. Calling ``_apply_similarity_gate``
    directly cannot detect that guard coming back, so drive the caller."""

    @pytest.mark.parametrize("history", [None, {}, ["a flat list is not a per-platform dict"]])
    async def test_a_run_without_usable_history_still_logs_the_event(
        self, service: Any, caplog: pytest.LogCaptureFixture, history: Any
    ) -> None:
        caplog.set_level(logging.INFO, logger="publisher_v2.services.ai")
        service.generator = _MultiGenerator()

        captions, sd_caption, _usages = await service.create_multi_caption_pair_from_analysis(
            _analysis(), {"telegram": _spec()}, history=history
        )

        assert captions == {"telegram": "a caption"}
        assert sd_caption is None
        events = [r.getMessage() for r in caplog.records if "caption_similarity" in r.getMessage()]
        assert events, caplog.text
        assert '"history_size": 0' in events[0]
        assert '"max_similarity": 0.0' in events[0]
        assert service.generator.calls == [None], "no regeneration may fire without history"
