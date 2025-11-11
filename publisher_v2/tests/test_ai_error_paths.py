from __future__ import annotations

import json
import pytest

from publisher_v2.config.schema import OpenAIConfig
from publisher_v2.core.exceptions import AIServiceError
from publisher_v2.core.models import CaptionSpec, ImageAnalysis
from publisher_v2.services.ai import VisionAnalyzerOpenAI, CaptionGeneratorOpenAI


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


class _CompletionsBadJSON:
    async def create(self, model: str, messages, response_format, temperature: float):
        # Return a non-JSON blob to trigger fallback
        return _Resp("Not JSON at all")


class _CompletionsCaption:
    def __init__(self, content: str) -> None:
        self._content = content

    async def create(self, model: str, messages, response_format=None, temperature: float = 0.7):
        return _Resp(self._content)


class _ClientWithCompletions:
    def __init__(self, completions) -> None:
        self.chat = type("Chat", (), {"completions": completions})()


@pytest.mark.asyncio
async def test_analyzer_fallback_non_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _ClientWithCompletions(_CompletionsBadJSON()))
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx")
    analyzer = VisionAnalyzerOpenAI(cfg)
    out = await analyzer.analyze("http://tmp-url")
    assert isinstance(out, ImageAnalysis)
    # Fallback should fill minimal fields
    assert out.description != ""
    assert out.mood == "unknown"
    assert out.tags == []
    assert out.nsfw is False
    assert out.safety_labels == []


@pytest.mark.asyncio
async def test_analyzer_rejects_bytes_input(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx")
    analyzer = VisionAnalyzerOpenAI(cfg)
    with pytest.raises(AIServiceError):
        await analyzer.analyze(b"\x01\x02")


@pytest.mark.asyncio
async def test_caption_generate_enforces_length(monkeypatch: pytest.MonkeyPatch) -> None:
    long_text = "x" * 500
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _ClientWithCompletions(_CompletionsCaption(long_text)))
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx")
    gen = CaptionGeneratorOpenAI(cfg)
    spec = CaptionSpec(platform="generic", style="style", hashtags="", max_length=50)
    text = await gen.generate(ImageAnalysis(description="d", mood="m", tags=[], nsfw=False, safety_labels=[]), spec)
    assert len(text) <= 50
    assert text.endswith("…")


@pytest.mark.asyncio
async def test_generate_with_sd_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"caption": "short", "sd_caption": "sd prompt"}
    monkeypatch.setattr(
        "publisher_v2.services.ai.AsyncOpenAI",
        lambda api_key: _ClientWithCompletions(_CompletionsCaption(json.dumps(payload))),
    )
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx")
    gen = CaptionGeneratorOpenAI(cfg)
    spec = CaptionSpec(platform="generic", style="style", hashtags="", max_length=50)
    out = await gen.generate_with_sd(ImageAnalysis(description="d", mood="m", tags=[], nsfw=False, safety_labels=[]), spec)
    assert out["caption"] == "short"
    assert out["sd_caption"] == "sd prompt"





