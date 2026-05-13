from __future__ import annotations

import json

import pytest

from publisher_v2.config.schema import OpenAIConfig
from publisher_v2.core.exceptions import AIServiceError
from publisher_v2.core.models import CaptionSpec, ImageAnalysis
from publisher_v2.services.ai import CaptionGeneratorOpenAI, VisionAnalyzerOpenAI


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

    async def create(self, **kwargs):  # accepts max_tokens added in PUB-046
        return _Resp(self._content)


class _ClientWithCompletions:
    def __init__(self, completions) -> None:
        self.chat = type("Chat", (), {"completions": completions})()


@pytest.mark.asyncio
async def test_analyzer_non_json_response_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Post-hardening: non-JSON Vision response surfaces an AIServiceError.

    Previously this path fabricated an analysis with ``description=content[:100]``,
    which let attacker-controlled model output (e.g. overlay text in the image
    or a jailbroken model) flow into downstream caption generation. The new
    behavior surfaces the failure so the caller can decide (retry/skip)."""
    monkeypatch.setattr(
        "publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _ClientWithCompletions(_CompletionsBadJSON())
    )
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_max_dimension=0, vision_fallback_enabled=False)
    analyzer = VisionAnalyzerOpenAI(cfg)
    with pytest.raises(AIServiceError):
        await analyzer.analyze("http://tmp-url")


@pytest.mark.asyncio
async def test_analyzer_rejects_bytes_input(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_max_dimension=0, vision_fallback_enabled=False)
    analyzer = VisionAnalyzerOpenAI(cfg)
    with pytest.raises(AIServiceError):
        await analyzer.analyze(b"\x01\x02")


@pytest.mark.asyncio
async def test_caption_generate_enforces_length(monkeypatch: pytest.MonkeyPatch) -> None:
    long_text = "x" * 500
    monkeypatch.setattr(
        "publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _ClientWithCompletions(_CompletionsCaption(long_text))
    )
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_max_dimension=0, vision_fallback_enabled=False)
    gen = CaptionGeneratorOpenAI(cfg)
    spec = CaptionSpec(platform="generic", style="style", hashtags="", max_length=50)
    text, _usage = await gen.generate(
        ImageAnalysis(description="d", mood="m", tags=[], nsfw=False, safety_labels=[]), spec
    )
    assert len(text) <= 50
    assert text.endswith("…")


@pytest.mark.asyncio
async def test_generate_with_sd_parses_json(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {"caption": "short", "sd_caption": "sd prompt"}
    monkeypatch.setattr(
        "publisher_v2.services.ai.AsyncOpenAI",
        lambda api_key: _ClientWithCompletions(_CompletionsCaption(json.dumps(payload))),
    )
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_max_dimension=0, vision_fallback_enabled=False)
    gen = CaptionGeneratorOpenAI(cfg)
    spec = CaptionSpec(platform="generic", style="style", hashtags="", max_length=50)
    out, _usage = await gen.generate_with_sd(
        ImageAnalysis(description="d", mood="m", tags=[], nsfw=False, safety_labels=[]), spec
    )
    assert out["caption"] == "short"
    assert out["sd_caption"] == "sd prompt"
