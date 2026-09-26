"""Tests for multi-platform caption generation (AC1-8, AC13-15)."""

from __future__ import annotations

import json

import pytest
from conftest import BaseDummyAnalyzer

from publisher_v2.config.schema import OpenAIConfig
from publisher_v2.core.exceptions import AIServiceError
from publisher_v2.core.models import CaptionSpec, ImageAnalysis
from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI

# --- Mock helpers ---


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


class _Choice:
    def __init__(self, content: str) -> None:
        self.message = _Msg(content)


class _Resp:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(content)]


class _FakeCompletions:
    """Capture create() calls and return configured response."""

    def __init__(self, response_content: str) -> None:
        self._response_content = response_content
        self.calls: list[dict] = []

    async def create(self, **kwargs) -> _Resp:
        self.calls.append(kwargs)
        return _Resp(self._response_content)


class _FakeClient:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.chat = type("Chat", (), {"completions": completions})()


def _make_specs() -> dict[str, CaptionSpec]:
    return {
        "telegram": CaptionSpec(
            platform="telegram", style="conversational, emoji-friendly", hashtags="#shibari #ropeart", max_length=4096
        ),
        "instagram": CaptionSpec(
            platform="instagram", style="hook-first, hashtags naturally", hashtags="#shibari #ropeart", max_length=2200
        ),
        "email": CaptionSpec(platform="email", style="engagement question", hashtags="", max_length=240),
    }


def _make_analysis() -> ImageAnalysis:
    return ImageAnalysis(
        description="Fine-art portrait with soft light",
        mood="calm",
        tags=["portrait", "softlight"],
    )


def _default_config() -> OpenAIConfig:
    return OpenAIConfig(
        api_key="sk-test",
        vision_model="gpt-4o",
        caption_model="gpt-4o-mini",
        sd_caption_enabled=True,
        sd_caption_single_call_enabled=True,
    )


# --- AC1: generate_multi returns dict per platform ---


class TestGenerateMulti:
    @pytest.mark.asyncio
    async def test_generate_multi_returns_dict_per_platform(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC1: Single call returns dict[str, str] keyed by platform."""
        response = json.dumps(
            {
                "telegram": "Telegram caption here",
                "instagram": "Instagram caption here",
                "email": "Email caption here",
            }
        )
        completions = _FakeCompletions(response)
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _FakeClient(completions))

        gen = CaptionGeneratorOpenAI(_default_config())
        specs = _make_specs()
        result, _usage = await gen.generate_multi(_make_analysis(), specs)

        assert isinstance(result, dict)
        assert set(result.keys()) == {"telegram", "instagram", "email"}
        assert result["telegram"] == "Telegram caption here"

    @pytest.mark.asyncio
    async def test_single_openai_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC1: Only one OpenAI API call is made for all platforms."""
        response = json.dumps(
            {
                "telegram": "t",
                "instagram": "i",
                "email": "e",
            }
        )
        completions = _FakeCompletions(response)
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _FakeClient(completions))

        gen = CaptionGeneratorOpenAI(_default_config())
        _result, _usage = await gen.generate_multi(_make_analysis(), _make_specs())

        assert len(completions.calls) == 1

    @pytest.mark.asyncio
    async def test_caption_truncated_when_exceeds_max_length(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC2: Captions exceeding max_length are truncated with ellipsis."""
        long_email = "x" * 500  # email max_length is 240
        response = json.dumps(
            {
                "telegram": "short",
                "instagram": "short",
                "email": long_email,
            }
        )
        completions = _FakeCompletions(response)
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _FakeClient(completions))

        gen = CaptionGeneratorOpenAI(_default_config())
        result, _usage = await gen.generate_multi(_make_analysis(), _make_specs())

        assert len(result["email"]) <= 240
        assert result["email"].endswith("…")

    @pytest.mark.asyncio
    async def test_missing_platform_key_raises_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC3: Missing platform key in LLM response raises AIServiceError."""
        response = json.dumps(
            {
                "telegram": "t",
                # missing instagram and email
            }
        )
        completions = _FakeCompletions(response)
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _FakeClient(completions))

        gen = CaptionGeneratorOpenAI(_default_config())
        with pytest.raises(AIServiceError, match="Missing platform.*instagram"):
            await gen.generate_multi(_make_analysis(), _make_specs())

    @pytest.mark.asyncio
    async def test_uses_json_response_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC4: Uses response_format=json_object."""
        response = json.dumps({"telegram": "t", "instagram": "i", "email": "e"})
        completions = _FakeCompletions(response)
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _FakeClient(completions))

        gen = CaptionGeneratorOpenAI(_default_config())
        _result, _usage = await gen.generate_multi(_make_analysis(), _make_specs())

        call = completions.calls[0]
        assert call["response_format"] == {"type": "json_object"}


# --- AC5-7: Platform style directives in prompt ---


class TestPlatformStylesInPrompt:
    @pytest.mark.asyncio
    async def test_telegram_style_in_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC5: Telegram prompt includes conversational style."""
        response = json.dumps({"telegram": "t"})
        completions = _FakeCompletions(response)
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _FakeClient(completions))

        gen = CaptionGeneratorOpenAI(_default_config())
        specs = {
            "telegram": CaptionSpec(
                platform="telegram", style="conversational, emoji-friendly", hashtags="#tag", max_length=4096
            )
        }
        _result, _usage = await gen.generate_multi(_make_analysis(), specs)

        user_msg = completions.calls[0]["messages"][-1]["content"]
        assert "conversational" in user_msg.lower()

    @pytest.mark.asyncio
    async def test_instagram_style_in_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC6: Instagram prompt includes hook-first style."""
        response = json.dumps({"instagram": "i"})
        completions = _FakeCompletions(response)
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _FakeClient(completions))

        gen = CaptionGeneratorOpenAI(_default_config())
        specs = {
            "instagram": CaptionSpec(
                platform="instagram", style="hook-first, hashtags naturally", hashtags="#tag", max_length=2200
            )
        }
        _result, _usage = await gen.generate_multi(_make_analysis(), specs)

        user_msg = completions.calls[0]["messages"][-1]["content"]
        assert "hook-first" in user_msg.lower()

    @pytest.mark.asyncio
    async def test_email_style_in_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC7 / PUB-046 AC-11: Email prompt reflects new sentence+question style."""
        response = json.dumps({"email": "e"})
        completions = _FakeCompletions(response)
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _FakeClient(completions))

        gen = CaptionGeneratorOpenAI(_default_config())
        specs = {
            "email": CaptionSpec(
                platform="email",
                style="one intimate sentence + one brief question, FetLife-appropriate, no hashtags",
                hashtags="",
                max_length=240,
            )
        }
        _result, _usage = await gen.generate_multi(_make_analysis(), specs)

        user_msg = completions.calls[0]["messages"][-1]["content"].lower()
        assert "sentence" in user_msg
        assert "question" in user_msg


# --- AC13-15 (PUB-025): SD caption integration ---
# PUB-051 AC4/AC5 removed sd_caption from the caption-stage completion: it now comes
# from the neutral vision call. TestGenerateMultiWithSD (AC13 captions+sd from one
# completion, AC14 its sd format, AC15 fallback from the sd completion to
# generate_multi) asserted exactly that removed behaviour and is deleted; the
# replacement contract is test_caption_call_requests_platform_keys_only_no_sd_caption
# below and the vision-stage tests in test_ai_vision_analysis_telemetry.py.


# --- AIService.create_multi_caption_pair_from_analysis ---


class TestCreateMultiCaptionPair:
    # PUB-051 AC4: test_returns_captions_and_sd (sd_caption returned from the caption
    # stage's generate_multi_with_sd) asserted the removed behaviour and is deleted.

    @pytest.mark.asyncio
    async def test_sd_disabled_uses_generate_multi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = OpenAIConfig(
            api_key="sk-test",
            sd_caption_enabled=False,
            sd_caption_single_call_enabled=False,
        )
        gen = CaptionGeneratorOpenAI(cfg)

        async def _fake_multi(analysis, specs, **kwargs):
            return {k: f"{k}-only" for k in specs}, None

        monkeypatch.setattr(gen, "generate_multi", _fake_multi)

        analyzer = BaseDummyAnalyzer()
        ai = AIService(analyzer=analyzer, generator=gen)  # type: ignore[arg-type]

        specs = _make_specs()
        # PUB-051: the per-platform angles are the fourth element of the return.
        captions, sd, _usages, _angles = await ai.create_multi_caption_pair_from_analysis(_make_analysis(), specs)

        assert captions["telegram"] == "telegram-only"
        assert sd is None


# --- PUB-051 AC4: the caption completion asks for platform keys only, at the new sampling values ---


async def _drive_caption_call(monkeypatch: pytest.MonkeyPatch, response: dict[str, str]):
    """Real AIService with the default (sd-enabled) config; returns (result, recorded calls)."""
    from publisher_v2.services.ai import VisionAnalyzerOpenAI

    completions = _FakeCompletions(json.dumps(response))
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _FakeClient(completions))
    cfg = _default_config()
    service = AIService(VisionAnalyzerOpenAI(cfg), CaptionGeneratorOpenAI(cfg))
    result = await service.create_multi_caption_pair_from_analysis(_make_analysis(), _make_specs())
    return result, completions.calls


async def test_caption_call_requests_platform_keys_only_no_sd_caption(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC4: the prompt's key list and the parsed dict are the enabled platforms only.

    The fake model volunteers an ``sd_caption`` anyway: it must be neither requested
    nor parsed — sd_caption comes from the vision stage now (AC5).
    """
    specs = _make_specs()
    result, calls = await _drive_caption_call(
        monkeypatch, {"telegram": "t", "instagram": "i", "email": "e", "sd_caption": "volunteered"}
    )

    assert len(calls) == 1, "one caption completion; no separate sd_caption call on the caption path"
    call = calls[0]
    system = call["messages"][0]["content"]
    user = call["messages"][-1]["content"]
    assert "sd_caption" not in user
    assert "sd_caption" not in system
    for platform in specs:
        assert f'"{platform}"' in user, f"{platform} missing from the requested keys"
    assert call["response_format"] == {"type": "json_object"}

    captions, sd_caption, _usages, angles = result
    assert set(captions) == set(specs)
    assert sd_caption is None, "the caption stage must not be a source of sd_caption"
    assert set(angles) == set(specs)


async def test_caption_call_sampling_params_match_configured_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC4 + Scope: temperature 0.9, frequency_penalty 0.3, presence_penalty 0.6 on the actual create() call."""
    from publisher_v2.services.ai import (
        CAPTION_FREQUENCY_PENALTY,
        CAPTION_PRESENCE_PENALTY,
        DEFAULT_CAPTION_TEMPERATURE,
    )

    assert (DEFAULT_CAPTION_TEMPERATURE, CAPTION_FREQUENCY_PENALTY, CAPTION_PRESENCE_PENALTY) == (0.9, 0.3, 0.6)

    _result, calls = await _drive_caption_call(monkeypatch, {"telegram": "t", "instagram": "i", "email": "e"})

    assert len(calls) == 1
    call = calls[0]
    assert call["temperature"] == DEFAULT_CAPTION_TEMPERATURE
    assert call["frequency_penalty"] == CAPTION_FREQUENCY_PENALTY
    assert call["presence_penalty"] == CAPTION_PRESENCE_PENALTY
