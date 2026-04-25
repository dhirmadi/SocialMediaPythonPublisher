from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import pytest

from publisher_v2.config.schema import OpenAIConfig
from publisher_v2.core.models import ImageAnalysis
from publisher_v2.services.ai import VisionAnalyzerOpenAI
from publisher_v2.utils.captions import build_metadata_phase2
from publisher_v2.utils.preview import print_vision_analysis
from publisher_v2.web.models import AnalysisResponse
from publisher_v2.web.service import WebImageService


def test_imageanalysis_accepts_alt_text_default_none() -> None:
    analysis = ImageAnalysis(description="x", mood="y")
    assert getattr(analysis, "alt_text", None) is None


def test_imageanalysis_accepts_alt_text_value() -> None:
    analysis = ImageAnalysis(description="x", mood="y", alt_text="A person standing by a window.")
    assert analysis.alt_text == "A person standing by a window."


def test_default_vision_prompts_include_alt_text() -> None:
    from publisher_v2.services import ai as ai_mod

    assert "alt_text" in ai_mod._DEFAULT_VISION_SYSTEM_PROMPT
    assert "alt_text" in ai_mod._DEFAULT_VISION_USER_PROMPT
    assert "125" in ai_mod._DEFAULT_VISION_SYSTEM_PROMPT
    assert "screen readers" in ai_mod._DEFAULT_VISION_SYSTEM_PROMPT.lower()


class _DummyMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _DummyChoice:
    def __init__(self, message: _DummyMessage) -> None:
        self.message = message


class _DummyResp:
    def __init__(self, content: str) -> None:
        self.choices = [_DummyChoice(_DummyMessage(content))]


def _make_dummy_client(content: str):
    class _DummyCompletions:
        async def create(
            self, model: str, messages, response_format, temperature: float, max_tokens: int | None = None
        ):
            return _DummyResp(content)

    class _DummyClient:
        def __init__(self) -> None:
            self.chat = SimpleNamespace(completions=_DummyCompletions())

    return _DummyClient()


@pytest.mark.asyncio
async def test_vision_analyzer_parses_alt_text(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(
        {
            "description": "test scene",
            "mood": "calm",
            "tags": ["t1"],
            "nsfw": False,
            "safety_labels": [],
            "alt_text": "A person sitting on a chair in soft light.",
        }
    )
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _make_dummy_client(payload))
    cfg = OpenAIConfig(api_key="sk-test", vision_max_dimension=0, vision_fallback_enabled=False)
    analyzer = VisionAnalyzerOpenAI(cfg)
    analysis, _usage = await analyzer.analyze("http://tmp-url")

    assert analysis.alt_text == "A person sitting on a chair in soft light."


@pytest.mark.asyncio
async def test_vision_analyzer_missing_alt_text_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.dumps(
        {
            "description": "test scene",
            "mood": "calm",
            "tags": ["t1"],
            "nsfw": False,
            "safety_labels": [],
        }
    )
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _make_dummy_client(payload))
    cfg = OpenAIConfig(api_key="sk-test", vision_max_dimension=0, vision_fallback_enabled=False)
    analyzer = VisionAnalyzerOpenAI(cfg)
    analysis, _usage = await analyzer.analyze("http://tmp-url")

    assert analysis.alt_text is None


@pytest.mark.asyncio
async def test_vision_analyzer_json_decode_error_sets_alt_text_none(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _make_dummy_client("not-json"))
    cfg = OpenAIConfig(api_key="sk-test", vision_max_dimension=0, vision_fallback_enabled=False)
    analyzer = VisionAnalyzerOpenAI(cfg)
    analysis, _usage = await analyzer.analyze("http://tmp-url")

    assert analysis.alt_text is None


def test_build_metadata_phase2_includes_alt_text_when_present() -> None:
    analysis = ImageAnalysis(description="x", mood="y", alt_text="A person holding a rope harness.")
    meta = build_metadata_phase2(analysis)
    assert meta["alt_text"] == "A person holding a rope harness."


def test_build_metadata_phase2_omits_alt_text_when_none() -> None:
    analysis = ImageAnalysis(description="x", mood="y")
    meta = build_metadata_phase2(analysis)
    assert "alt_text" not in meta


def test_analysis_response_model_has_alt_text_field() -> None:
    fields = getattr(AnalysisResponse, "model_fields", {})
    assert "alt_text" in fields


@pytest.mark.asyncio
async def test_web_analyze_and_caption_returns_alt_text_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    # Avoid invoking WebImageService.__init__ (which loads env/config). Build a minimal instance.
    svc = WebImageService.__new__(WebImageService)
    svc.logger = logging.getLogger("test")
    svc._usage_meter = None

    svc.config = SimpleNamespace(
        storage_paths=SimpleNamespace(image_folder="/images"),
        features=SimpleNamespace(analyze_caption_enabled=True, alt_text_enabled=True),
        content=SimpleNamespace(debug=False),
    )

    class _Storage:
        async def get_temporary_link(self, folder: str, filename: str) -> str:
            return "http://tmp-url"

        async def download_sidecar_if_exists(self, folder: str, filename: str):
            return None

    svc.storage = _Storage()

    analysis = ImageAnalysis(description="d", mood="m", tags=[], nsfw=False, safety_labels=[], alt_text="Alt here.")

    class _Analyzer:
        async def analyze(self, temp_link: str):
            return analysis, None

    class _AI:
        analyzer = _Analyzer()

        async def create_multi_caption_pair_from_analysis(self, analysis: ImageAnalysis, specs, history=None):
            return {"telegram": "cap"}, None, []

        async def create_caption_from_analysis(self, analysis: ImageAnalysis, spec):
            return "cap", []

    async def _ensure_ai_service():
        return _AI()

    svc._ensure_ai_service = _ensure_ai_service  # type: ignore[assignment]

    from publisher_v2.core.models import CaptionSpec

    monkeypatch.setattr(
        CaptionSpec,
        "for_platforms",
        lambda _cfg: {"telegram": CaptionSpec(platform="telegram", style="x", hashtags="", max_length=10)},
    )

    resp = await svc.analyze_and_caption("x.jpg", correlation_id="c", force_refresh=True)
    assert resp.alt_text == "Alt here."


def test_preview_print_vision_analysis_includes_alt_text(capsys: pytest.CaptureFixture[str]) -> None:
    analysis = ImageAnalysis(description="d", mood="m", tags=[], nsfw=False, safety_labels=[], alt_text="Alt here.")
    print_vision_analysis(analysis, model="gpt-test", feature_enabled=True)
    out = capsys.readouterr().out
    assert "Alt text:" in out
    assert "Alt here." in out


# ---------------------------------------------------------------------------
# AC-06 / AC-07: WorkflowOrchestrator._build_publisher_context feature gate
# ---------------------------------------------------------------------------


def _orchestrator_with_alt_text_enabled(enabled: bool):
    """Build a minimal WorkflowOrchestrator instance with the alt_text flag set."""
    from publisher_v2.core.workflow import WorkflowOrchestrator

    orchestrator = WorkflowOrchestrator.__new__(WorkflowOrchestrator)
    orchestrator.config = SimpleNamespace(features=SimpleNamespace(alt_text_enabled=enabled))
    return orchestrator


def test_ac06_context_includes_alt_text_when_enabled_and_present() -> None:
    """AC-06: alt_text_enabled=True + analysis.alt_text non-None → context has alt_text."""
    orchestrator = _orchestrator_with_alt_text_enabled(True)
    analysis = ImageAnalysis(
        description="d", mood="m", tags=["a", "b"], nsfw=False, safety_labels=[], alt_text="A person at a window."
    )

    context = orchestrator._build_publisher_context(analysis)

    assert context is not None
    assert context["alt_text"] == "A person at a window."
    assert context["analysis_tags"] == ["a", "b"]


def test_ac07_context_omits_alt_text_when_disabled() -> None:
    """AC-07: alt_text_enabled=False → no alt_text key, even when analysis has one."""
    orchestrator = _orchestrator_with_alt_text_enabled(False)
    analysis = ImageAnalysis(
        description="d", mood="m", tags=["a"], nsfw=False, safety_labels=[], alt_text="A person at a window."
    )

    context = orchestrator._build_publisher_context(analysis)

    assert context is not None
    assert "alt_text" not in context
    assert context["analysis_tags"] == ["a"]


def test_context_omits_alt_text_when_enabled_but_none() -> None:
    """AC-06 negative case: enabled but analysis.alt_text is None → no alt_text key."""
    orchestrator = _orchestrator_with_alt_text_enabled(True)
    analysis = ImageAnalysis(description="d", mood="m", tags=["a"], nsfw=False, safety_labels=[], alt_text=None)

    context = orchestrator._build_publisher_context(analysis)

    assert context is not None
    assert "alt_text" not in context


def test_context_is_none_when_analysis_is_none() -> None:
    """When no analysis exists, the context is None (publishers receive no context)."""
    orchestrator = _orchestrator_with_alt_text_enabled(True)
    assert orchestrator._build_publisher_context(None) is None
