"""Tests for PUB-041 vision cost optimization (resize + detail + fallback + config)."""

from __future__ import annotations

import base64
import io
import json
import logging
from typing import Any
from unittest.mock import AsyncMock

import pytest
from PIL import Image
from pydantic import ValidationError

from publisher_v2.config.schema import OpenAIConfig
from publisher_v2.core.exceptions import AIServiceError
from publisher_v2.core.models import AIUsage, ImageAnalysis
from publisher_v2.services.ai import VisionAnalyzerOpenAI
from publisher_v2.utils.images import resize_image_bytes

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_jpeg(width: int, height: int, color: tuple[int, int, int] = (200, 100, 50)) -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def _make_png_with_alpha(width: int, height: int) -> bytes:
    img = Image.new("RGBA", (width, height), color=(0, 200, 100, 128))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


VALID_VISION_JSON = json.dumps(
    {
        "description": "test scene",
        "mood": "calm",
        "tags": ["t1"],
        "nsfw": False,
        "safety_labels": [],
    }
)


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeUsage:
    def __init__(self, total: int = 100) -> None:
        self.total_tokens = total
        self.prompt_tokens = total - 20
        self.completion_tokens = 20


class _FakeResp:
    def __init__(self, content: str, usage_total: int = 100, resp_id: str = "resp_test") -> None:
        self.choices = [_FakeChoice(content)]
        self.usage = _FakeUsage(usage_total)
        self.id = resp_id


def _set_create_mock(analyzer: VisionAnalyzerOpenAI, mock: AsyncMock) -> None:
    chat_ns = type("Chat", (), {})()
    completions_ns = type("Completions", (), {})()
    completions_ns.create = mock
    chat_ns.completions = completions_ns
    analyzer.client = chat_ns  # type: ignore[assignment]
    # AsyncOpenAI client has shape client.chat.completions.create — mimic via attr access
    # Actual client is replaced wholesale.
    parent = type("ClientWrap", (), {})()
    parent.chat = chat_ns
    analyzer.client = parent  # type: ignore[assignment]


@pytest.fixture
def patch_retry_wait(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace tenacity wait_exponential strategy with zero-wait so retries do not slow tests."""
    import tenacity.wait

    class _NoWait(tenacity.wait.wait_base):
        def __call__(self, retry_state: object) -> float:  # noqa: ARG002
            return 0.0

    # Override the wait method on existing wait_exponential instances by patching the class
    monkeypatch.setattr(tenacity.wait.wait_exponential, "__call__", lambda self, retry_state: 0.0)


@pytest.fixture
def patch_httpx_download(monkeypatch: pytest.MonkeyPatch):
    """Patch httpx.AsyncClient used inside VisionAnalyzerOpenAI to return controlled bytes."""

    def _install(image_bytes: bytes) -> dict[str, Any]:
        calls: dict[str, Any] = {"count": 0, "urls": []}

        class _FakeResp:
            def __init__(self, content: bytes) -> None:
                self.content = content

            def raise_for_status(self) -> None:
                return None

        class _FakeClient:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def __aenter__(self) -> _FakeClient:
                return self

            async def __aexit__(self, *args: Any) -> None:
                return None

            async def get(self, url: str, timeout: float | None = None) -> _FakeResp:  # noqa: ASYNC109
                calls["count"] += 1
                calls["urls"].append(url)
                return _FakeResp(image_bytes)

        import httpx

        monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
        return calls

    return _install


# ---------------------------------------------------------------------------
# resize_image_bytes (AC-06)
# ---------------------------------------------------------------------------


class TestResizeImageBytes:
    def test_resize_large_image_to_max_dimension(self) -> None:
        src = _make_jpeg(4000, 6000)
        out = resize_image_bytes(src, max_dimension=1024)
        img = Image.open(io.BytesIO(out))
        assert max(img.size) == 1024
        # 4000x6000 -> longest is 6000; scale = 1024/6000; 4000*scale ≈ 682.67 -> 683
        assert img.size == (683, 1024)
        assert img.format == "JPEG"

    def test_does_not_upscale_small_image(self) -> None:
        src = _make_jpeg(800, 600)
        out = resize_image_bytes(src, max_dimension=1024)
        img = Image.open(io.BytesIO(out))
        assert img.size == (800, 600)
        assert img.format == "JPEG"

    def test_png_with_alpha_converted_to_rgb_jpeg(self) -> None:
        src = _make_png_with_alpha(500, 400)
        out = resize_image_bytes(src, max_dimension=1024)
        img = Image.open(io.BytesIO(out))
        assert img.format == "JPEG"
        assert img.mode == "RGB"

    def test_quality_param_applied(self) -> None:
        src = _make_jpeg(2000, 2000, color=(123, 200, 50))
        small = resize_image_bytes(src, max_dimension=1024, quality=20)
        large = resize_image_bytes(src, max_dimension=1024, quality=95)
        # Higher quality => larger output bytes (in general, monotonic for the same image)
        assert len(large) > len(small)

    def test_aspect_ratio_preserved(self) -> None:
        src = _make_jpeg(3000, 1500)
        out = resize_image_bytes(src, max_dimension=1024)
        img = Image.open(io.BytesIO(out))
        # 3000:1500 = 2:1 ; 1024 / 0.5 = 1024x512
        assert img.size == (1024, 512)


# ---------------------------------------------------------------------------
# Config (AC-17, AC-18, AC-20)
# ---------------------------------------------------------------------------


class TestOpenAIConfigVisionFields:
    def test_ac17_defaults(self) -> None:
        cfg = OpenAIConfig()
        assert cfg.vision_max_dimension == 1024
        assert cfg.vision_detail == "low"
        assert cfg.vision_fallback_enabled is True
        assert cfg.vision_fallback_max_dimension == 2048
        assert cfg.vision_fallback_detail == "high"

    def test_ac18_validator_rejects_invalid_detail(self) -> None:
        with pytest.raises(ValidationError):
            OpenAIConfig(vision_detail="bad")
        with pytest.raises(ValidationError):
            OpenAIConfig(vision_fallback_detail="garbage")

    def test_ac18_validator_accepts_low_high_auto(self) -> None:
        for v in ("low", "high", "auto"):
            cfg = OpenAIConfig(vision_detail=v, vision_fallback_detail=v)
            assert cfg.vision_detail == v
            assert cfg.vision_fallback_detail == v


class TestStandaloneLoaderEnv:
    def test_ac20_openai_settings_parses_vision_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from publisher_v2.config.loader import _load_openai_settings_from_env

        payload = {
            "vision_model": "gpt-4o",
            "caption_model": "gpt-4o-mini",
            "sd_caption_enabled": True,
            "sd_caption_single_call_enabled": True,
            "vision_max_dimension": 768,
            "vision_detail": "auto",
            "vision_fallback_enabled": False,
            "vision_fallback_max_dimension": 1500,
            "vision_fallback_detail": "high",
        }
        monkeypatch.setenv("OPENAI_SETTINGS", json.dumps(payload))
        result = _load_openai_settings_from_env()
        assert result is not None
        assert result["vision_max_dimension"] == 768
        assert result["vision_detail"] == "auto"
        assert result["vision_fallback_enabled"] is False
        assert result["vision_fallback_max_dimension"] == 1500
        assert result["vision_fallback_detail"] == "high"

    def test_ac20_openai_settings_defaults_when_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from publisher_v2.config.loader import _load_openai_settings_from_env

        payload = {
            "vision_model": "gpt-4o",
            "caption_model": "gpt-4o-mini",
            "sd_caption_enabled": True,
            "sd_caption_single_call_enabled": True,
        }
        monkeypatch.setenv("OPENAI_SETTINGS", json.dumps(payload))
        result = _load_openai_settings_from_env()
        assert result is not None
        assert result["vision_max_dimension"] == 1024
        assert result["vision_detail"] == "low"
        assert result["vision_fallback_enabled"] is True


# ---------------------------------------------------------------------------
# Orchestrator mapping (AC-19)
# ---------------------------------------------------------------------------


class TestOrchestratorAIMapping:
    def test_ac19_orchestrator_v2_maps_vision_fields(self) -> None:
        from publisher_v2.config.orchestrator_models import OrchestratorAI

        ai = OrchestratorAI(
            credentials_ref="cred:test",
            vision_max_dimension=768,
            vision_detail="auto",
            vision_fallback_enabled=False,
            vision_fallback_max_dimension=1500,
            vision_fallback_detail="high",
        )
        assert ai.vision_max_dimension == 768
        assert ai.vision_detail == "auto"
        assert ai.vision_fallback_enabled is False
        assert ai.vision_fallback_max_dimension == 1500
        assert ai.vision_fallback_detail == "high"

    def test_ac19_build_app_config_v2_maps_vision_fields(self) -> None:
        """AC-19: apply_orchestrator_ai_to_openai_cfg copies vision fields onto OpenAIConfig.

        ``_build_app_config_v2`` delegates to this helper, so testing the helper
        directly verifies the mapping without booting the full credential pipeline.
        """
        from publisher_v2.config.orchestrator_models import OrchestratorAI
        from publisher_v2.config.source import apply_orchestrator_ai_to_openai_cfg

        ai = OrchestratorAI(
            credentials_ref="cred:openai",
            vision_max_dimension=512,
            vision_detail="auto",
            vision_fallback_enabled=False,
            vision_fallback_max_dimension=4096,
            vision_fallback_detail="high",
        )
        openai_cfg = OpenAIConfig()
        apply_orchestrator_ai_to_openai_cfg(ai, openai_cfg)

        assert openai_cfg.vision_max_dimension == 512
        assert openai_cfg.vision_detail == "auto"
        assert openai_cfg.vision_fallback_enabled is False
        assert openai_cfg.vision_fallback_max_dimension == 4096
        assert openai_cfg.vision_fallback_detail == "high"

    def test_ac19_absent_vision_fields_keep_defaults(self) -> None:
        """AC-19: Absent fields on OrchestratorAI leave OpenAIConfig defaults intact."""
        from publisher_v2.config.orchestrator_models import OrchestratorAI
        from publisher_v2.config.source import apply_orchestrator_ai_to_openai_cfg

        ai = OrchestratorAI(credentials_ref="cred:openai")  # no vision_* fields
        openai_cfg = OpenAIConfig()
        apply_orchestrator_ai_to_openai_cfg(ai, openai_cfg)

        # Schema defaults preserved
        assert openai_cfg.vision_max_dimension == 1024
        assert openai_cfg.vision_detail == "low"
        assert openai_cfg.vision_fallback_enabled is True
        assert openai_cfg.vision_fallback_max_dimension == 2048
        assert openai_cfg.vision_fallback_detail == "high"


# ---------------------------------------------------------------------------
# Vision analyzer behaviour (AC-01..AC-05, AC-21)
# ---------------------------------------------------------------------------


def _build_analyzer(**cfg_overrides: Any) -> VisionAnalyzerOpenAI:
    cfg = OpenAIConfig(api_key="sk-test-key-for-testing", **cfg_overrides)
    return VisionAnalyzerOpenAI(cfg)


def _stub_client_create(analyzer: VisionAnalyzerOpenAI, content: str = VALID_VISION_JSON) -> AsyncMock:
    """Replace analyzer.client with a stub whose .chat.completions.create is an AsyncMock."""
    mock = AsyncMock(return_value=_FakeResp(content))

    completions = type("Completions", (), {})()
    completions.create = mock
    chat = type("Chat", (), {})()
    chat.completions = completions
    parent = type("ClientWrap", (), {})()
    parent.chat = chat
    analyzer.client = parent  # type: ignore[assignment]
    return mock


class TestAnalyzeResizeAndDetail:
    async def test_ac01_resizes_4000x6000_and_sends_data_url(self, patch_httpx_download) -> None:
        src_bytes = _make_jpeg(4000, 6000)
        calls = patch_httpx_download(src_bytes)

        analyzer = _build_analyzer(vision_max_dimension=1024, vision_detail="low")
        create_mock = _stub_client_create(analyzer)

        analysis, usage = await analyzer.analyze("https://signed.example.com/image.jpg")
        assert isinstance(analysis, ImageAnalysis)
        assert calls["count"] == 1

        kwargs = create_mock.call_args.kwargs
        messages = kwargs["messages"]
        # Find the image part
        user_msg = messages[1]
        image_part = next(p for p in user_msg["content"] if p["type"] == "image_url")
        url = image_part["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")
        b64 = url.split(",", 1)[1]
        decoded = base64.b64decode(b64)
        img = Image.open(io.BytesIO(decoded))
        assert max(img.size) == 1024
        assert img.size == (683, 1024)

    async def test_ac02_detail_field_matches_config(self, patch_httpx_download) -> None:
        patch_httpx_download(_make_jpeg(2000, 2000))
        analyzer = _build_analyzer(vision_max_dimension=1024, vision_detail="low")
        create_mock = _stub_client_create(analyzer)

        await analyzer.analyze("https://x.example.com/p.jpg")
        kwargs = create_mock.call_args.kwargs
        image_part = next(p for p in kwargs["messages"][1]["content"] if p["type"] == "image_url")
        assert image_part["image_url"]["detail"] == "low"

    async def test_ac03_zero_max_dimension_passes_url_directly(
        self, patch_httpx_download, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = patch_httpx_download(_make_jpeg(2000, 2000))
        analyzer = _build_analyzer(vision_max_dimension=0, vision_detail="high")
        create_mock = _stub_client_create(analyzer)

        url = "https://signed.example.com/no-resize.jpg"
        await analyzer.analyze(url)
        # No download should occur when max_dimension == 0
        assert calls["count"] == 0
        kwargs = create_mock.call_args.kwargs
        image_part = next(p for p in kwargs["messages"][1]["content"] if p["type"] == "image_url")
        assert image_part["image_url"]["url"] == url
        assert image_part["image_url"]["detail"] == "high"

    async def test_ac04_small_image_no_upscale_still_data_url(self, patch_httpx_download) -> None:
        patch_httpx_download(_make_jpeg(800, 600))
        analyzer = _build_analyzer(vision_max_dimension=1024, vision_detail="low")
        create_mock = _stub_client_create(analyzer)

        await analyzer.analyze("https://x.example.com/small.jpg")
        kwargs = create_mock.call_args.kwargs
        image_part = next(p for p in kwargs["messages"][1]["content"] if p["type"] == "image_url")
        url = image_part["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")
        decoded = base64.b64decode(url.split(",", 1)[1])
        img = Image.open(io.BytesIO(decoded))
        assert img.size == (800, 600)
        assert img.format == "JPEG"

    async def test_ac05_aspect_ratio_preserved(self, patch_httpx_download) -> None:
        patch_httpx_download(_make_jpeg(4000, 6000))
        analyzer = _build_analyzer(vision_max_dimension=1024, vision_detail="low")
        create_mock = _stub_client_create(analyzer)

        await analyzer.analyze("https://x.example.com/aspect.jpg")
        kwargs = create_mock.call_args.kwargs
        image_part = next(p for p in kwargs["messages"][1]["content"] if p["type"] == "image_url")
        decoded = base64.b64decode(image_part["image_url"]["url"].split(",", 1)[1])
        img = Image.open(io.BytesIO(decoded))
        # 4000:6000 = 2:3 -> 683:1024 (within 1px)
        assert abs(img.size[0] / img.size[1] - 2 / 3) < 0.01

    async def test_ac21_legacy_behavior_no_resize_high_detail(self, patch_httpx_download) -> None:
        """AC-21: max_dim=0, detail='high' restores pre-PUB-041 behavior."""
        calls = patch_httpx_download(_make_jpeg(4000, 6000))
        analyzer = _build_analyzer(vision_max_dimension=0, vision_detail="high")
        create_mock = _stub_client_create(analyzer)

        url = "https://signed.example.com/legacy.jpg"
        await analyzer.analyze(url)
        assert calls["count"] == 0  # no download
        kwargs = create_mock.call_args.kwargs
        image_part = next(p for p in kwargs["messages"][1]["content"] if p["type"] == "image_url")
        assert image_part["image_url"]["url"] == url
        assert image_part["image_url"]["detail"] == "high"


# ---------------------------------------------------------------------------
# Fallback (AC-07..AC-11)
# ---------------------------------------------------------------------------


class _ScriptedCompletions:
    """OpenAI completions stub that returns scripted responses or raises errors per call."""

    def __init__(self, script: list[Any]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def create(self, *args: Any, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        nxt = self._script.pop(0) if self._script else _FakeResp(VALID_VISION_JSON)
        if isinstance(nxt, BaseException):
            raise nxt
        return nxt


def _install_scripted(analyzer: VisionAnalyzerOpenAI, script: list[Any]) -> _ScriptedCompletions:
    completions = _ScriptedCompletions(script)
    chat = type("Chat", (), {})()
    chat.completions = completions
    parent = type("ClientWrap", (), {})()
    parent.chat = chat
    analyzer.client = parent  # type: ignore[assignment]
    return completions


class TestFallback:
    async def test_ac07_fallback_called_with_higher_settings_on_aiservice_error(
        self, patch_httpx_download, patch_retry_wait
    ) -> None:
        downloads = patch_httpx_download(_make_jpeg(4000, 6000))
        analyzer = _build_analyzer(
            vision_max_dimension=1024,
            vision_detail="low",
            vision_fallback_enabled=True,
            vision_fallback_max_dimension=2048,
            vision_fallback_detail="high",
        )
        # primary 3 retries fail, fallback 1st succeeds
        primary_err = RuntimeError("primary failed")
        good = _FakeResp(VALID_VISION_JSON, usage_total=200, resp_id="fallback-resp")
        completions = _install_scripted(
            analyzer,
            [primary_err, primary_err, primary_err, good],
        )

        analysis, usage = await analyzer.analyze("https://signed.example.com/image.jpg")
        assert isinstance(analysis, ImageAnalysis)
        # 3 primary attempts + 1 fallback attempt = 4 OpenAI calls total
        assert len(completions.calls) == 4
        # Fallback used detail='high' on the last call (and primary used detail='low')
        last_call = completions.calls[-1]
        image_part = next(p for p in last_call["messages"][1]["content"] if p["type"] == "image_url")
        assert image_part["image_url"]["detail"] == "high"
        first_call = completions.calls[0]
        first_image = next(p for p in first_call["messages"][1]["content"] if p["type"] == "image_url")
        assert first_image["image_url"]["detail"] == "low"
        # Download is done ONCE per chain (primary + fallback) — retries reuse the data URL
        assert downloads["count"] == 2

    async def test_ac08_fallback_warning_log_emitted(
        self, patch_httpx_download, patch_retry_wait, caplog: pytest.LogCaptureFixture
    ) -> None:
        patch_httpx_download(_make_jpeg(2000, 2000))
        analyzer = _build_analyzer()
        primary_err = RuntimeError("simulated primary fail")
        good = _FakeResp(VALID_VISION_JSON)
        _install_scripted(analyzer, [primary_err, primary_err, primary_err, good])

        caplog.set_level(logging.WARNING, logger="publisher_v2.ai.vision")
        await analyzer.analyze("https://x.example.com/p.jpg")

        warnings = [r for r in caplog.records if "vision_fallback_triggered" in r.message]
        assert warnings, "expected vision_fallback_triggered log"
        payload = json.loads(warnings[0].message)
        assert payload["event"] == "vision_fallback_triggered"
        assert "original_error" in payload

    async def test_ac09_fallback_disabled_raises_aiservice_error(self, patch_httpx_download, patch_retry_wait) -> None:
        patch_httpx_download(_make_jpeg(2000, 2000))
        analyzer = _build_analyzer(vision_fallback_enabled=False)
        primary_err = RuntimeError("primary failed")
        _install_scripted(analyzer, [primary_err, primary_err, primary_err])

        with pytest.raises(AIServiceError):
            await analyzer.analyze("https://x.example.com/p.jpg")

    async def test_ac09_fallback_also_fails_raises_aiservice_error(
        self, patch_httpx_download, patch_retry_wait
    ) -> None:
        patch_httpx_download(_make_jpeg(2000, 2000))
        analyzer = _build_analyzer(vision_fallback_enabled=True)
        err = RuntimeError("boom")
        # 3 primary + 3 fallback = 6 errors
        _install_scripted(analyzer, [err] * 6)

        with pytest.raises(AIServiceError):
            await analyzer.analyze("https://x.example.com/p.jpg")

    async def test_ac10_fallback_adds_at_most_one_additional_call_chain(
        self, patch_httpx_download, patch_retry_wait
    ) -> None:
        patch_httpx_download(_make_jpeg(2000, 2000))
        analyzer = _build_analyzer()
        # Fallback succeeds on first attempt of its chain
        primary_err = RuntimeError("primary failed")
        good = _FakeResp(VALID_VISION_JSON)
        completions = _install_scripted(analyzer, [primary_err, primary_err, primary_err, good])

        await analyzer.analyze("https://x.example.com/p.jpg")
        # At most 3 primary + 3 fallback = 6 calls upper bound; this scenario expects exactly 4
        assert len(completions.calls) == 4

    async def test_ac11_returns_combined_usage(self, patch_httpx_download, patch_retry_wait) -> None:
        patch_httpx_download(_make_jpeg(2000, 2000))
        analyzer = _build_analyzer()
        primary_err = RuntimeError("primary failed")
        good = _FakeResp(VALID_VISION_JSON, usage_total=300, resp_id="fb-resp")
        _install_scripted(analyzer, [primary_err, primary_err, primary_err, good])

        analysis, usage = await analyzer.analyze("https://x.example.com/p.jpg")
        assert isinstance(analysis, ImageAnalysis)
        # When fallback fires, the combined usage should reflect both calls.
        # Primary usage may be zero (errors had no usage); fallback should contribute 300.
        assert usage is not None
        assert isinstance(usage, AIUsage)
        assert usage.total_tokens >= 300
