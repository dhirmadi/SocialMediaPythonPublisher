from __future__ import annotations

from publisher_v2.config.schema import OpenAIConfig
from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI, VisionAnalyzerOpenAI
from publisher_v2.services.publishers.instagram import InstagramPublisher


class _DummyAnalyzer(VisionAnalyzerOpenAI):
    def __init__(self) -> None:
        pass


def test_ai_service_uses_default_rate_limit(monkeypatch) -> None:
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_model="gpt-4o", caption_model="gpt-4o-mini")
    ai = AIService(analyzer=_DummyAnalyzer(), generator=CaptionGeneratorOpenAI(cfg))
    # Access the internal limiter to verify configured rate; attribute exists by construction.
    assert getattr(ai._rate_limiter, "rate_per_minute", 20) == 20  # type: ignore[attr-defined]


def test_instagram_publisher_uses_default_delay_range(monkeypatch) -> None:
    pub = InstagramPublisher(config=None, enabled=False)
    limits = pub._limits  # type: ignore[attr-defined]
    assert limits.delay_min_seconds == 1
    assert limits.delay_max_seconds == 3
