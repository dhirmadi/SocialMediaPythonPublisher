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
