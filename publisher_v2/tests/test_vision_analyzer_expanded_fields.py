from __future__ import annotations

import json

import pytest

from publisher_v2.config.schema import OpenAIConfig
from publisher_v2.services.ai import VisionAnalyzerOpenAI

_EXPANDED_PAYLOAD = {
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


@pytest.mark.asyncio
async def test_analyzer_parses_expanded_fields(fake_openai) -> None:
    fake_openai(script=[_EXPANDED_PAYLOAD])
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


def _detail_payload(include_detail: bool) -> dict:
    payload: dict = {
        "description": "A composed portrait.",
        "mood": "bold",
        "tags": ["portrait"],
        "nsfw": False,
        "safety_labels": [],
    }
    if include_detail:
        payload["distinctive_detail"] = "a single red thread tied around the left wrist"
    return payload


@pytest.mark.asyncio
async def test_analyzer_parses_distinctive_detail(fake_openai) -> None:
    fake_openai(script=[_detail_payload(True)])
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_max_dimension=0, vision_fallback_enabled=False)
    analyzer = VisionAnalyzerOpenAI(cfg)
    result, _usage = await analyzer.analyze("http://tmp-url")
    assert result.distinctive_detail == "a single red thread tied around the left wrist"


@pytest.mark.asyncio
async def test_analyzer_distinctive_detail_none_safe(fake_openai) -> None:
    fake_openai(script=[_detail_payload(False)])
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_max_dimension=0, vision_fallback_enabled=False)
    analyzer = VisionAnalyzerOpenAI(cfg)
    result, _usage = await analyzer.analyze("http://tmp-url")
    assert result.distinctive_detail is None


# ---------- #138: caption-facing sensory_detail + mood_note ----------


_WARM_PAYLOAD = {
    "description": "Figure in a jute harness against a grey wall.",
    "mood": "calm",
    "tags": ["rope"],
    "nsfw": True,
    "safety_labels": ["bondage_or_restraints"],
    "alt_text": "A person in a rope harness.",
    "sensory_detail": ["the jute pressing a shallow line into warm skin", "breath held at the last wrap"],
    "mood_note": "It feels like the quiet second before someone lets go.",
}


async def _warm_analysis(fake_openai):
    fake = fake_openai(script=[_WARM_PAYLOAD])
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_max_dimension=0, vision_fallback_enabled=False)
    result, _usage = await VisionAnalyzerOpenAI(cfg).analyze("http://tmp-url")
    return result, fake


async def test_vision_prompt_requests_caption_facing_fields(fake_openai) -> None:
    _result, fake = await _warm_analysis(fake_openai)
    sent = json.dumps(fake.calls[-1]["messages"])
    assert "sensory_detail" in sent
    assert "mood_note" in sent


async def test_sensory_detail_and_mood_note_parsed(fake_openai) -> None:
    result, _ = await _warm_analysis(fake_openai)
    assert result.sensory_detail == [
        "the jute pressing a shallow line into warm skin",
        "breath held at the last wrap",
    ]
    assert result.mood_note == "It feels like the quiet second before someone lets go."


async def test_caption_facing_fields_come_first_in_analysis_context(fake_openai) -> None:
    from publisher_v2.services.ai import build_analysis_context

    result, _ = await _warm_analysis(fake_openai)
    context = build_analysis_context(result)
    assert context.startswith("sensory_detail=")
    assert context.index("mood_note=") < context.index("description=")


async def test_caption_facing_fields_absent_from_sidecar_metadata(fake_openai) -> None:
    from publisher_v2.services.sidecar_parser import rehydrate_sidecar_view
    from publisher_v2.utils.captions import build_caption_sidecar, build_metadata_phase2

    result, _ = await _warm_analysis(fake_openai)
    text = build_caption_sidecar("rope, figure", build_metadata_phase2(result))
    view = rehydrate_sidecar_view(text)
    assert "sensory_detail" not in text and "mood_note" not in text
    assert "sensory_detail" not in (view.get("metadata") or {})
    assert "mood_note" not in (view.get("metadata") or {})


async def test_sensory_detail_string_is_kept_as_one_item(fake_openai) -> None:
    fake_openai(script=[{"description": "d", "mood": "m", "sensory_detail": "cool jute on a warm wrist"}])
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_max_dimension=0, vision_fallback_enabled=False)
    result, _ = await VisionAnalyzerOpenAI(cfg).analyze("http://tmp-url")
    assert result.sensory_detail == ["cool jute on a warm wrist"]
