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
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _DummyClient())
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_max_dimension=0, vision_fallback_enabled=False)
    analyzer = VisionAnalyzerOpenAI(cfg)
    result, _usage = await analyzer.analyze("http://tmp-url")

    assert result.description.startswith("A composed")
    assert result.mood == "bold"
    assert result.tags == ["portrait", "fashion"]
    assert result.nsfw is True
    assert result.safety_labels == ["nudity"]
    # New optional fields
    assert result.subject is not None
    assert result.style == "fine-art editorial"
    assert result.lighting == "soft directional"
    assert result.camera.startswith("50mm")  # type: ignore[union-attr]
    assert result.clothing_or_accessories == "rope harness"
    assert result.aesthetic_terms == ["minimalist", "graphic"]
    assert result.pose == "upright stance"
    assert "center-weighted" in (result.composition or "")
    assert "studio" in (result.background or "")
    assert "black" in (result.color_palette or "")


# ---------- #81 (CAP-4): distinctive_detail ----------


class _DetailCompletions:
    def __init__(self, include_detail: bool) -> None:
        self._include = include_detail

    async def create(self, model: str, messages, response_format, temperature: float):
        payload: dict = {
            "description": "A composed portrait.",
            "mood": "bold",
            "tags": ["portrait"],
            "nsfw": False,
            "safety_labels": [],
        }
        if self._include:
            payload["distinctive_detail"] = "a single red thread tied around the left wrist"
        return _DummyResp(json.dumps(payload))


class _DetailClient:
    def __init__(self, include_detail: bool) -> None:
        completions = _DetailCompletions(include_detail)
        self.chat = type("Chat", (), {"completions": completions})()


@pytest.mark.asyncio
async def test_analyzer_parses_distinctive_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _DetailClient(True))
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_max_dimension=0, vision_fallback_enabled=False)
    analyzer = VisionAnalyzerOpenAI(cfg)
    result, _usage = await analyzer.analyze("http://tmp-url")
    assert result.distinctive_detail == "a single red thread tied around the left wrist"


@pytest.mark.asyncio
async def test_analyzer_distinctive_detail_none_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _DetailClient(False))
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_max_dimension=0, vision_fallback_enabled=False)
    analyzer = VisionAnalyzerOpenAI(cfg)
    result, _usage = await analyzer.analyze("http://tmp-url")
    assert result.distinctive_detail is None


# ---------- #138: caption-facing sensory_detail + mood_note ----------


class _WarmCompletions:
    def __init__(self) -> None:
        self.messages: list = []

    async def create(self, model: str, messages, response_format, temperature: float):
        self.messages = messages
        payload = {
            "description": "Figure in a jute harness against a grey wall.",
            "mood": "calm",
            "tags": ["rope"],
            "nsfw": True,
            "safety_labels": ["bondage_or_restraints"],
            "alt_text": "A person in a rope harness.",
            "sensory_detail": ["the jute pressing a shallow line into warm skin", "breath held at the last wrap"],
            "mood_note": "It feels like the quiet second before someone lets go.",
        }
        return _DummyResp(json.dumps(payload))


class _WarmClient:
    def __init__(self, completions: _WarmCompletions) -> None:
        self.chat = type("Chat", (), {"completions": completions})()


async def _warm_analysis(monkeypatch: pytest.MonkeyPatch):
    completions = _WarmCompletions()
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _WarmClient(completions))
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_max_dimension=0, vision_fallback_enabled=False)
    result, _usage = await VisionAnalyzerOpenAI(cfg).analyze("http://tmp-url")
    return result, completions


async def test_vision_prompt_requests_caption_facing_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    _result, completions = await _warm_analysis(monkeypatch)
    sent = json.dumps(completions.messages)
    assert "sensory_detail" in sent
    assert "mood_note" in sent


async def test_sensory_detail_and_mood_note_parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    result, _ = await _warm_analysis(monkeypatch)
    assert result.sensory_detail == [
        "the jute pressing a shallow line into warm skin",
        "breath held at the last wrap",
    ]
    assert result.mood_note == "It feels like the quiet second before someone lets go."


async def test_caption_facing_fields_come_first_in_analysis_context(monkeypatch: pytest.MonkeyPatch) -> None:
    from publisher_v2.services.ai import build_analysis_context

    result, _ = await _warm_analysis(monkeypatch)
    context = build_analysis_context(result)
    assert context.startswith("sensory_detail=")
    assert context.index("mood_note=") < context.index("description=")


async def test_caption_facing_fields_absent_from_sidecar_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    from publisher_v2.services.sidecar_parser import rehydrate_sidecar_view
    from publisher_v2.utils.captions import build_caption_sidecar, build_metadata_phase2

    result, _ = await _warm_analysis(monkeypatch)
    text = build_caption_sidecar("rope, figure", build_metadata_phase2(result))
    view = rehydrate_sidecar_view(text)
    assert "sensory_detail" not in text and "mood_note" not in text
    assert "sensory_detail" not in (view.get("metadata") or {})
    assert "mood_note" not in (view.get("metadata") or {})


async def test_sensory_detail_string_is_kept_as_one_item(monkeypatch: pytest.MonkeyPatch) -> None:
    completions = _WarmCompletions()

    async def _create(model: str, messages, response_format, temperature: float):
        return _DummyResp(json.dumps({"description": "d", "mood": "m", "sensory_detail": "cool jute on a warm wrist"}))

    completions.create = _create  # type: ignore[method-assign]
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _WarmClient(completions))
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_max_dimension=0, vision_fallback_enabled=False)
    result, _ = await VisionAnalyzerOpenAI(cfg).analyze("http://tmp-url")
    assert result.sensory_detail == ["cool jute on a warm wrist"]
