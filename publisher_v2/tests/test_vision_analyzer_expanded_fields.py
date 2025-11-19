from __future__ import annotations

import json
import pytest

from publisher_v2.config.schema import OpenAIConfig
from publisher_v2.services.ai import VisionAnalyzerOpenAI


class _DummyMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _DummyChoice:
    def __init__(self, message: _DummyMessage) -> None:
        self.message = message


class _DummyResp:
    def __init__(self, content: str) -> None:
        self.choices = [_DummyChoice(_DummyMessage(content))]


class _DummyCompletions:
    async def create(self, model: str, messages, response_format, temperature: float):
        payload = {
            "description": "A composed portrait with rope harness.",
            "mood": "bold",
            "tags": ["portrait", "fashion"],
            "nsfw": True,
            "safety_labels": ["nudity"],
            "subject": "single adult subject, torso framed",
            "style": "fine-art editorial",
            "lighting": "soft directional",
            "camera": "50mm equivalent",
            "clothing_or_accessories": "rope harness",
            "aesthetic_terms": ["minimalist", "graphic"],
            "pose": "upright stance",
            "composition": "center-weighted portrait",
            "background": "plain studio backdrop",
            "color_palette": "black, white, gray",
        }
        return _DummyResp(json.dumps(payload))


class _DummyClient:
    def __init__(self) -> None:
        self.chat = type("Chat", (), {"completions": _DummyCompletions()})()


@pytest.mark.asyncio
async def test_analyzer_parses_expanded_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    # Monkeypatch AsyncOpenAI client used inside VisionAnalyzerOpenAI
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _DummyClient())
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx")
    analyzer = VisionAnalyzerOpenAI(cfg)
    result = await analyzer.analyze("http://tmp-url")

    assert result.description.startswith("A composed")
    assert result.mood == "bold"
    assert result.tags == ["portrait", "fashion"]
    assert result.nsfw is True
    assert result.safety_labels == ["nudity"]
    # New optional fields
    assert result.subject is not None
    assert result.style == "fine-art editorial"
    assert result.lighting == "soft directional"
    assert result.camera.startswith("50mm")
    assert result.clothing_or_accessories == "rope harness"
    assert result.aesthetic_terms == ["minimalist", "graphic"]
    assert result.pose == "upright stance"
    assert "center-weighted" in (result.composition or "")
    assert "studio" in (result.background or "")
    assert "black" in (result.color_palette or "")





