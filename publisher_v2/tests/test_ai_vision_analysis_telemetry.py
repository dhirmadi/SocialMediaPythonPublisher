from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import pytest

from publisher_v2.config.schema import OpenAIConfig
from publisher_v2.core.models import ImageAnalysis
from publisher_v2.services.ai import VisionAnalyzerOpenAI


class _FakeRespMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeRespMessage(content)


class _FakeResp:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeChatCompletions:
    def __init__(self, content: str, delay_ms: float = 0) -> None:
        self._content = content
        self._delay_ms = delay_ms

    async def create(self, *args: Any, **kwargs: Any) -> _FakeResp:
        # Simulate minimal delay to exercise timing
        if self._delay_ms:
            await asyncio.sleep(self._delay_ms / 1000.0)
        return _FakeResp(self._content)


class _FakeAsyncOpenAI:
    def __init__(self, content: str, delay_ms: float = 0) -> None:
        self.chat = type("Chat", (), {})()
        self.chat.completions = _FakeChatCompletions(content, delay_ms=delay_ms)


def _build_config() -> OpenAIConfig:
    # Minimal viable OpenAIConfig for analyzer; tests do not hit real network.
    return OpenAIConfig(
        api_key="sk-test",
        vision_model="gpt-4.1-mini",
        caption_model="gpt-4.1-mini",
    )


@pytest.mark.asyncio
async def test_vision_analyzer_logs_timing_success(monkeypatch, caplog) -> None:
    config = _build_config()
    analyzer = VisionAnalyzerOpenAI(config)

    fake_client = _FakeAsyncOpenAI(
        json.dumps(
            {
                "description": "short description",
                "mood": "calm",
                "tags": ["tag1", "tag2"],
                "nsfw": False,
                "safety_labels": [],
            }
        )
    )
    monkeypatch.setattr(analyzer, "client", fake_client)

    caplog.set_level(logging.INFO, logger="publisher_v2.ai.vision")

    analysis = await analyzer.analyze("http://example.com/image.jpg")
    assert isinstance(analysis, ImageAnalysis)

    telemetry_logs = [
        record
        for record in caplog.records
        if "vision_analysis" in getattr(record, "message", "")
    ]
    assert telemetry_logs, "expected at least one telemetry log_json entry"

    # Parse last telemetry JSON entry
    payload = json.loads(telemetry_logs[-1].message)
    assert payload.get("event") == "vision_analysis"
    assert payload.get("model") == config.vision_model
    assert payload.get("ok") is True
    assert payload.get("error_type") is None
    assert payload.get("vision_analysis_ms", 0) >= 0


@pytest.mark.asyncio
async def test_vision_analyzer_logs_timing_on_json_error(monkeypatch, caplog) -> None:
    config = _build_config()
    analyzer = VisionAnalyzerOpenAI(config)

    # Force non-JSON content to trigger fallback path
    fake_client = _FakeAsyncOpenAI("not-json")
    monkeypatch.setattr(analyzer, "client", fake_client)

    caplog.set_level(logging.INFO, logger="publisher_v2.ai.vision")

    analysis = await analyzer.analyze("http://example.com/image.jpg")
    assert isinstance(analysis, ImageAnalysis)

    telemetry_logs = [
        record
        for record in caplog.records
        if "vision_analysis" in getattr(record, "message", "")
    ]
    assert telemetry_logs, "expected telemetry log_json even on JSON error"

    payload = json.loads(telemetry_logs[-1].message)
    assert payload.get("event") == "vision_analysis"
    assert payload.get("ok") is True  # Fallback still produces an ImageAnalysis
    # json_decode_error should be recorded when fallback was used
    assert payload.get("error_type") in (None, "json_decode_error")

