from __future__ import annotations

import pytest

from publisher_v2.config.schema import OpenAIConfig
from publisher_v2.core.models import CaptionSpec, ImageAnalysis
from publisher_v2.services.ai import CaptionGeneratorOpenAI, AIService

# Use centralized test fixtures from conftest.py (QC-001)
from conftest import BaseDummyAnalyzer


@pytest.mark.asyncio
async def test_ai_generate_with_sd_pair_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_model="gpt-4o", caption_model="gpt-4o-mini")

    gen = CaptionGeneratorOpenAI(cfg)

    async def fake_generate_with_sd(analysis: ImageAnalysis, spec: CaptionSpec) -> dict[str, str]:
        return {"caption": "c", "sd_caption": "s"}

    monkeypatch.setattr(gen, "generate_with_sd", fake_generate_with_sd)

    ai = AIService(analyzer=BaseDummyAnalyzer(), generator=gen)

    spec = CaptionSpec(platform="generic", style="minimal", hashtags="#tag", max_length=100)
    caption, sd_caption = await ai.create_caption_pair("http://tmp", spec)

    assert caption == "c"
    assert sd_caption == "s"
    # Basic PG-13 shape: no explicit content; here we just ensure non-empty string
    assert isinstance(sd_caption, str) and len(sd_caption) > 0


@pytest.mark.asyncio
async def test_ai_generate_with_sd_from_existing_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_model="gpt-4o", caption_model="gpt-4o-mini")

    gen = CaptionGeneratorOpenAI(cfg)

    async def fake_generate_with_sd(analysis: ImageAnalysis, spec: CaptionSpec) -> dict[str, str]:
        return {"caption": "from-analysis", "sd_caption": "from-analysis-sd"}

    monkeypatch.setattr(gen, "generate_with_sd", fake_generate_with_sd)

    analyzer = BaseDummyAnalyzer()
    ai = AIService(analyzer=analyzer, generator=gen)

    spec = CaptionSpec(platform="generic", style="minimal", hashtags="#tag", max_length=100)
    analysis = await analyzer.analyze("http://tmp")

    caption, sd_caption = await ai.create_caption_pair_from_analysis(analysis, spec)

    assert caption == "from-analysis"
    assert sd_caption == "from-analysis-sd"


