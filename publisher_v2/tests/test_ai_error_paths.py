from __future__ import annotations

import json

import pytest
from conftest import BaseDummyStorage

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
        "publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _ClientWithCompletions(_CompletionsBadJSON())
    )
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_max_dimension=0, vision_fallback_enabled=False)
    analyzer = VisionAnalyzerOpenAI(cfg)
    with pytest.raises(AIServiceError):
        await analyzer.analyze("http://tmp-url")


@pytest.mark.asyncio
async def test_analyzer_rejects_invalid_bytes_input(monkeypatch: pytest.MonkeyPatch) -> None:
    """#93 changed the contract: bytes ARE supported now (resized locally,
    never fetched) — but bytes that don't decode as an image still fail."""
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_max_dimension=1024, vision_fallback_enabled=False)
    analyzer = VisionAnalyzerOpenAI(cfg)
    with pytest.raises(AIServiceError):
        await analyzer.analyze(b"\x01\x02")


@pytest.mark.asyncio
async def test_caption_generate_enforces_length(monkeypatch: pytest.MonkeyPatch) -> None:
    long_text = "x" * 500
    monkeypatch.setattr(
        "publisher_v2.services.ai.AsyncOpenAI",
        lambda api_key, **kwargs: _ClientWithCompletions(_CompletionsCaption(long_text)),
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
        lambda api_key, **kwargs: _ClientWithCompletions(_CompletionsCaption(json.dumps(payload))),
    )
    cfg = OpenAIConfig(api_key="sk-xxxxxxxxxxxxxxxxxxxxxxxx", vision_max_dimension=0, vision_fallback_enabled=False)
    gen = CaptionGeneratorOpenAI(cfg)
    spec = CaptionSpec(platform="generic", style="style", hashtags="", max_length=50)
    out, _usage = await gen.generate_with_sd(
        ImageAnalysis(description="d", mood="m", tags=[], nsfw=False, safety_labels=[]), spec
    )
    assert out["caption"] == "short"
    assert out["sd_caption"] == "sd prompt"


# ---------- #84 (PERF-1): explicit timeout, one retry layer, hard deadline ----------


class TestClientConstruction:
    def test_clients_built_with_zero_sdk_retries_and_finite_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[dict] = []

        def _fake_async_openai(api_key=None, **kwargs):
            captured.append(kwargs)
            return _ClientWithCompletions(_CompletionsCaption("x"))

        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", _fake_async_openai)
        cfg = OpenAIConfig(api_key="sk-test")
        VisionAnalyzerOpenAI(cfg)
        CaptionGeneratorOpenAI(cfg)

        assert len(captured) == 2
        for kwargs in captured:
            assert kwargs.get("max_retries") == 0
            timeout = kwargs.get("timeout")
            assert timeout is not None
            # httpx.Timeout with a finite overall budget and 5s connect.
            assert getattr(timeout, "read", None) == 60.0
            assert getattr(timeout, "connect", None) == 5.0

    def test_request_timeout_configurable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[dict] = []

        def _fake_async_openai(api_key=None, **kwargs):
            captured.append(kwargs)
            return _ClientWithCompletions(_CompletionsCaption("x"))

        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", _fake_async_openai)
        cfg = OpenAIConfig(api_key="sk-test", request_timeout_seconds=25.0)
        VisionAnalyzerOpenAI(cfg)
        assert getattr(captured[0]["timeout"], "read", None) == 25.0


class TestStageDeadline:
    async def test_hanging_analyzer_fails_within_stage_deadline(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        import asyncio
        import time

        from publisher_v2.config.schema import (
            ApplicationConfig,
            ContentConfig,
            DropboxConfig,
            PlatformsConfig,
            StoragePathConfig,
        )
        from publisher_v2.core.workflow import WorkflowOrchestrator
        from publisher_v2.services.ai import AIService

        monkeypatch.setenv("AI_STAGE_TIMEOUT_SECONDS", "0.2")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))

        class _HangingAnalyzer:
            async def analyze(self, url_or_bytes):
                await asyncio.sleep(30)

        class _AI(AIService):
            def __init__(self) -> None:
                self.analyzer = _HangingAnalyzer()  # type: ignore[assignment]
                self.generator = None  # type: ignore[assignment]

        cfg = ApplicationConfig(
            dropbox=DropboxConfig(
                app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos", archive_folder="archive"
            ),
            storage_paths=StoragePathConfig(image_folder="/Photos"),
            openai=OpenAIConfig(api_key="sk-test"),
            platforms=PlatformsConfig(),
            content=ContentConfig(hashtag_string="", archive=False, debug=False),
        )
        orchestrator = WorkflowOrchestrator(cfg, BaseDummyStorage(), _AI(), [])

        start = time.monotonic()
        with pytest.raises(AIServiceError, match="ai stage timeout"):
            await orchestrator.execute()
        assert time.monotonic() - start < 5.0


# ---------- PUB-051 AC8: one same-resolution retry for a non-JSON vision reply ----------


@pytest.mark.asyncio
async def test_non_json_vision_reply_retried_once_at_same_resolution_before_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC8: a reply that fails JSON parsing is retried exactly once with the same image payload
    and detail, and only then falls through to the (different-resolution) fallback pass.

    Distinct from ``@_ai_retry``: that decorator retries transient transport errors (and
    backs off); a JSON-decode failure is not transient, so today it goes straight to the
    fallback. "Exactly once" also rules out routing it through ``@_ai_retry`` (3 attempts).
    Design-agnostic: counted per distinct system message, so a two-call vision stage
    (neutral + owner persona) is judged call by call.
    """
    import asyncio

    from caption_pipeline_fakes import (
        FakeOpenAI,
        default_vision_payload,
        image_part,
        jpeg_bytes,
        openai_config,
        system_text,
    )

    # No real backoff sleeps in this test, whatever path the code takes.
    async def _no_sleep(*_a, **_kw) -> None:
        return None

    monkeypatch.setattr(asyncio, "sleep", _no_sleep)

    def _payload(call_number: int, kwargs) -> str:
        part = image_part(kwargs)
        if part is not None and part.get("detail") == "low":
            return "Sorry, I can't produce JSON for this one."
        return default_vision_payload(call_number, kwargs)

    cfg = openai_config(
        vision_max_dimension=512,
        vision_detail="low",
        vision_fallback_enabled=True,
        vision_fallback_max_dimension=1024,
        vision_fallback_detail="high",
    )
    analyzer = VisionAnalyzerOpenAI(cfg)
    fake = FakeOpenAI([], vision_payload=_payload)
    monkeypatch.setattr(analyzer, "client", fake)

    analysis, _usage = await analyzer.analyze(jpeg_bytes(1600, 1200, (90, 60, 40)))

    calls = [c for c in fake.vision_calls if image_part(c) is not None]
    first_fallback = next(i for i, c in enumerate(calls) if image_part(c)["detail"] == "high")
    primary = calls[:first_fallback]
    assert primary, "no primary-resolution attempt was made"
    # Same resolution and detail on every pre-fallback attempt.
    assert {image_part(c)["detail"] for c in primary} == {"low"}
    assert len({image_part(c)["url"] for c in primary}) == 1, "the retry re-prepared the image at another size"
    assert image_part(calls[first_fallback])["url"] != image_part(primary[0])["url"], "fallback is not a new size"
    # Exactly one retry per vision call before falling through.
    per_call = {}
    for c in primary:
        per_call[system_text(c)] = per_call.get(system_text(c), 0) + 1
    assert set(per_call.values()) == {2}, f"attempts per vision call before fallback: {list(per_call.values())}"
    # The fallback path still produced an analysis.
    assert analysis.description
