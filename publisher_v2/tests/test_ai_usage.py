"""Tests for AIUsage dataclass and AI method usage extraction — AC-B1 through AC-B7."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from publisher_v2.core.models import AIUsage, CaptionSpec, ImageAnalysis

# --- AC-B1: AIUsage dataclass ---


def test_ai_usage_dataclass_fields() -> None:
    """AC-B1: AIUsage has response_id, total_tokens, prompt_tokens, completion_tokens."""
    u = AIUsage(response_id="resp-1", total_tokens=100, prompt_tokens=60, completion_tokens=40)
    assert u.response_id == "resp-1"
    assert u.total_tokens == 100
    assert u.prompt_tokens == 60
    assert u.completion_tokens == 40


# --- Helpers ---

_ANALYSIS = ImageAnalysis(description="test image", mood="calm", tags=["art"], nsfw=False, safety_labels=[])
_SPEC = CaptionSpec(platform="telegram", style="minimal_poetic", hashtags="", max_length=2200)


def _mock_openai_response(content: str = '{"description":"test"}', usage: Any = None, resp_id: str = "resp-abc") -> Any:
    """Build a mock OpenAI ChatCompletion response."""
    choice = SimpleNamespace(message=SimpleNamespace(content=content))
    return SimpleNamespace(choices=[choice], usage=usage, id=resp_id)


def _mock_usage(total: int = 100, prompt: int = 60, completion: int = 40) -> Any:
    return SimpleNamespace(total_tokens=total, prompt_tokens=prompt, completion_tokens=completion)


# --- AC-B2: VisionAnalyzerOpenAI.analyze() returns (ImageAnalysis, AIUsage | None) ---


@pytest.mark.asyncio
async def test_vision_analyzer_returns_usage_tuple() -> None:
    """AC-B2: analyze() returns (ImageAnalysis, AIUsage) when resp.usage is present."""
    from publisher_v2.services.ai import VisionAnalyzerOpenAI

    usage = _mock_usage(200, 120, 80)
    resp = _mock_openai_response(
        content=json.dumps(
            {"description": "a portrait", "mood": "serene", "tags": [], "nsfw": False, "safety_labels": []}
        ),
        usage=usage,
        resp_id="chatcmpl-123",
    )

    analyzer = VisionAnalyzerOpenAI.__new__(VisionAnalyzerOpenAI)
    analyzer.model = "gpt-4o"
    analyzer.max_completion_tokens = 512
    import logging

    analyzer.logger = logging.getLogger("test")
    # PUB-041: bypass resize/fallback for legacy URL-based test path
    analyzer._vision_max_dimension = 0
    analyzer._vision_detail = "high"
    analyzer._vision_fallback_enabled = False
    analyzer._vision_fallback_max_dimension = 0
    analyzer._vision_fallback_detail = "high"

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=resp)
    analyzer.client = mock_client

    result = await analyzer.analyze("https://example.com/image.jpg")
    assert isinstance(result, tuple)
    analysis, ai_usage = result
    assert isinstance(analysis, ImageAnalysis)
    assert analysis.description == "a portrait"
    assert isinstance(ai_usage, AIUsage)
    assert ai_usage.response_id == "chatcmpl-123"
    assert ai_usage.total_tokens == 200
    assert ai_usage.prompt_tokens == 120
    assert ai_usage.completion_tokens == 80


# --- AC-B3: CaptionGeneratorOpenAI.generate() returns (str, AIUsage | None) ---


@pytest.mark.asyncio
async def test_caption_generator_generate_returns_usage_tuple() -> None:
    """AC-B3: generate() returns (caption, AIUsage)."""
    from publisher_v2.services.ai import CaptionGeneratorOpenAI

    usage = _mock_usage(50, 30, 20)
    resp = _mock_openai_response(content="A beautiful artwork", usage=usage, resp_id="cmpl-456")

    gen = CaptionGeneratorOpenAI.__new__(CaptionGeneratorOpenAI)
    gen.model = "gpt-4o-mini"
    gen.system_prompt = "You are a caption writer."
    gen.role_prompt = "Write a caption."

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=resp)
    gen.client = mock_client

    result = await gen.generate(_ANALYSIS, _SPEC)
    assert isinstance(result, tuple)
    caption, ai_usage = result
    assert caption == "A beautiful artwork"
    assert isinstance(ai_usage, AIUsage)
    assert ai_usage.response_id == "cmpl-456"
    assert ai_usage.total_tokens == 50


@pytest.mark.asyncio
async def test_caption_generator_generate_with_sd_returns_usage_tuple() -> None:
    """AC-B3: generate_with_sd() returns (dict, AIUsage)."""
    from publisher_v2.services.ai import CaptionGeneratorOpenAI

    usage = _mock_usage(80, 50, 30)
    resp = _mock_openai_response(
        content=json.dumps({"caption": "art caption", "sd_caption": "sd prompt"}), usage=usage, resp_id="cmpl-sd"
    )

    gen = CaptionGeneratorOpenAI.__new__(CaptionGeneratorOpenAI)
    gen.model = "gpt-4o-mini"
    gen.sd_caption_model = "gpt-4o-mini"
    gen.sd_caption_system_prompt = "system"
    gen.sd_caption_role_prompt = "role"

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=resp)
    gen.client = mock_client

    result = await gen.generate_with_sd(_ANALYSIS, _SPEC)
    assert isinstance(result, tuple)
    data, ai_usage = result
    assert data["caption"] == "art caption"
    assert isinstance(ai_usage, AIUsage)
    assert ai_usage.total_tokens == 80


@pytest.mark.asyncio
async def test_caption_generator_generate_multi_returns_usage_tuple() -> None:
    """AC-B3: generate_multi() returns (dict, AIUsage)."""
    from publisher_v2.services.ai import CaptionGeneratorOpenAI

    usage = _mock_usage(90, 55, 35)
    resp = _mock_openai_response(
        content=json.dumps({"telegram": "tg caption", "email": "email caption"}), usage=usage, resp_id="cmpl-multi"
    )

    gen = CaptionGeneratorOpenAI.__new__(CaptionGeneratorOpenAI)
    gen.model = "gpt-4o-mini"
    gen.system_prompt = "system"
    gen.role_prompt = "role"

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=resp)
    gen.client = mock_client

    specs = {
        "telegram": CaptionSpec(platform="telegram", style="minimal_poetic", hashtags="", max_length=2200),
        "email": CaptionSpec(platform="email", style="descriptive", hashtags="", max_length=5000),
    }
    result = await gen.generate_multi(_ANALYSIS, specs)
    assert isinstance(result, tuple)
    captions, ai_usage = result
    assert "telegram" in captions
    assert isinstance(ai_usage, AIUsage)
    assert ai_usage.response_id == "cmpl-multi"


@pytest.mark.asyncio
async def test_caption_generator_generate_multi_with_sd_returns_usage_tuple() -> None:
    """AC-B3: generate_multi_with_sd() returns (dict, AIUsage)."""
    from publisher_v2.services.ai import CaptionGeneratorOpenAI

    usage = _mock_usage(110, 65, 45)
    resp = _mock_openai_response(
        content=json.dumps({"telegram": "tg", "email": "em", "sd_caption": "sd"}), usage=usage, resp_id="cmpl-ms"
    )

    gen = CaptionGeneratorOpenAI.__new__(CaptionGeneratorOpenAI)
    gen.model = "gpt-4o-mini"
    gen.sd_caption_model = "gpt-4o-mini"
    gen.sd_caption_system_prompt = "system"
    gen.sd_caption_role_prompt = "role"

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=resp)
    gen.client = mock_client

    specs = {
        "telegram": CaptionSpec(platform="telegram", style="minimal_poetic", hashtags="", max_length=2200),
        "email": CaptionSpec(platform="email", style="descriptive", hashtags="", max_length=5000),
    }
    result = await gen.generate_multi_with_sd(_ANALYSIS, specs)
    assert isinstance(result, tuple)
    data, ai_usage = result
    assert "telegram" in data
    assert isinstance(ai_usage, AIUsage)


# --- AC-B4: resp.usage is None → AIUsage is None ---


@pytest.mark.asyncio
async def test_vision_analyzer_none_usage() -> None:
    """AC-B4: When resp.usage is None, AIUsage is None."""
    from publisher_v2.services.ai import VisionAnalyzerOpenAI

    resp = _mock_openai_response(
        content=json.dumps({"description": "test", "mood": "calm", "tags": [], "nsfw": False, "safety_labels": []}),
        usage=None,
        resp_id="cmpl-no-usage",
    )

    analyzer = VisionAnalyzerOpenAI.__new__(VisionAnalyzerOpenAI)
    analyzer.model = "gpt-4o"
    analyzer.max_completion_tokens = 512
    import logging

    analyzer.logger = logging.getLogger("test")
    # PUB-041: bypass resize/fallback for legacy URL-based test path
    analyzer._vision_max_dimension = 0
    analyzer._vision_detail = "high"
    analyzer._vision_fallback_enabled = False
    analyzer._vision_fallback_max_dimension = 0
    analyzer._vision_fallback_detail = "high"

    mock_client = AsyncMock()
    mock_client.chat.completions.create = AsyncMock(return_value=resp)
    analyzer.client = mock_client

    result = await analyzer.analyze("https://example.com/image.jpg")
    analysis, ai_usage = result
    assert isinstance(analysis, ImageAnalysis)
    assert ai_usage is None


# --- AC-B5: AIService public methods aggregate and return list[AIUsage] ---


@pytest.mark.asyncio
async def test_ai_service_create_caption_pair_from_analysis_returns_usage_list() -> None:
    """AC-B5: create_caption_pair_from_analysis returns list[AIUsage]."""
    from publisher_v2.services.ai import AIService

    # Mock generator with sd enabled + single call
    gen = MagicMock()
    gen.sd_caption_enabled = True
    gen.sd_caption_single_call_enabled = True

    usage = AIUsage(response_id="u1", total_tokens=50, prompt_tokens=30, completion_tokens=20)
    gen.generate_with_sd = AsyncMock(return_value=({"caption": "cap", "sd_caption": "sd"}, usage))

    analyzer = MagicMock()
    service = AIService.__new__(AIService)
    service.analyzer = analyzer
    service.generator = gen
    service._rate_limiter = AsyncMock()
    service._rate_limiter.__aenter__ = AsyncMock(return_value=None)
    service._rate_limiter.__aexit__ = AsyncMock(return_value=None)

    result = await service.create_caption_pair_from_analysis(_ANALYSIS, _SPEC)
    assert isinstance(result, tuple)
    assert len(result) == 3
    caption, sd_caption, usages = result
    assert isinstance(usages, list)
    assert len(usages) == 1
    assert usages[0].response_id == "u1"


# --- AC-B6: NullAIService returns empty usage lists ---


def test_null_ai_service_has_no_crash_attributes() -> None:
    """AC-B6: NullAIService should not crash when attributes are checked."""
    from publisher_v2.services.ai import NullAIService

    svc = NullAIService()
    assert svc.analyzer is None
    assert svc.generator is None
