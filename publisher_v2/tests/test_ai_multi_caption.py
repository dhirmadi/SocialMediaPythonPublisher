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
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _FakeClient(completions))

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
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _FakeClient(completions))

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
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _FakeClient(completions))

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
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _FakeClient(completions))

        gen = CaptionGeneratorOpenAI(_default_config())
        with pytest.raises(AIServiceError, match="Missing platform.*instagram"):
            await gen.generate_multi(_make_analysis(), _make_specs())

    @pytest.mark.asyncio
    async def test_uses_json_response_format(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC4: Uses response_format=json_object."""
        response = json.dumps({"telegram": "t", "instagram": "i", "email": "e"})
        completions = _FakeCompletions(response)
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _FakeClient(completions))

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
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _FakeClient(completions))

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
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _FakeClient(completions))

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
        """AC7: Email prompt includes engagement question style."""
        response = json.dumps({"email": "e"})
        completions = _FakeCompletions(response)
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _FakeClient(completions))

        gen = CaptionGeneratorOpenAI(_default_config())
        specs = {
            "email": CaptionSpec(
                platform="email", style="engagement question, no hashtags", hashtags="", max_length=240
            )
        }
        _result, _usage = await gen.generate_multi(_make_analysis(), specs)

        user_msg = completions.calls[0]["messages"][-1]["content"]
        assert "engagement question" in user_msg.lower()


# --- AC13-15: SD caption integration ---


class TestGenerateMultiWithSD:
    @pytest.mark.asyncio
    async def test_generate_multi_with_sd_returns_captions_plus_sd(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC13: generate_multi_with_sd returns per-platform captions plus one sd_caption."""
        response = json.dumps(
            {
                "telegram": "t-caption",
                "instagram": "i-caption",
                "email": "e-caption",
                "sd_caption": "fine-art portrait, soft light, calm mood",
            }
        )
        completions = _FakeCompletions(response)
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _FakeClient(completions))

        gen = CaptionGeneratorOpenAI(_default_config())
        result, _usage = await gen.generate_multi_with_sd(_make_analysis(), _make_specs())

        assert result["telegram"] == "t-caption"
        assert result["instagram"] == "i-caption"
        assert result["email"] == "e-caption"
        assert result["sd_caption"] == "fine-art portrait, soft light, calm mood"

    @pytest.mark.asyncio
    async def test_sd_caption_format_unchanged(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC14: SD caption content/format is unchanged from existing pattern."""
        response = json.dumps(
            {
                "telegram": "t",
                "instagram": "i",
                "email": "e",
                "sd_caption": "PG-13 fine-art, pose upright, soft directional lighting",
            }
        )
        completions = _FakeCompletions(response)
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _FakeClient(completions))

        gen = CaptionGeneratorOpenAI(_default_config())
        result, _usage = await gen.generate_multi_with_sd(_make_analysis(), _make_specs())

        sd = result["sd_caption"]
        assert isinstance(sd, str)
        assert len(sd) > 0

    @pytest.mark.asyncio
    async def test_sd_fallback_to_generate_multi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC15: When SD fails, fallback to generate_multi returns (captions, None)."""
        cfg = _default_config()
        gen = CaptionGeneratorOpenAI(cfg)

        # Make generate_multi_with_sd fail
        async def _failing_sd(*args, **kwargs):
            raise AIServiceError("SD generation failed")

        # Make generate_multi succeed
        async def _ok_multi(analysis, specs, **kwargs):
            return {k: f"{k}-caption" for k in specs}, None

        monkeypatch.setattr(gen, "generate_multi_with_sd", _failing_sd)
        monkeypatch.setattr(gen, "generate_multi", _ok_multi)

        analyzer = BaseDummyAnalyzer()
        ai = AIService(analyzer=analyzer, generator=gen)  # type: ignore[arg-type]

        specs = _make_specs()
        captions, sd_caption, _usages = await ai.create_multi_caption_pair_from_analysis(_make_analysis(), specs)

        assert set(captions.keys()) == {"telegram", "instagram", "email"}
        assert sd_caption is None


# --- AIService.create_multi_caption_pair_from_analysis ---


class TestCreateMultiCaptionPair:
    @pytest.mark.asyncio
    async def test_returns_captions_and_sd(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg = _default_config()
        gen = CaptionGeneratorOpenAI(cfg)

        async def _fake_multi_sd(analysis, specs, **kwargs):
            result = {k: f"{k}-cap" for k in specs}
            result["sd_caption"] = "sd-text"
            return result, None

        monkeypatch.setattr(gen, "generate_multi_with_sd", _fake_multi_sd)

        analyzer = BaseDummyAnalyzer()
        ai = AIService(analyzer=analyzer, generator=gen)  # type: ignore[arg-type]

        specs = _make_specs()
        captions, sd, _usages = await ai.create_multi_caption_pair_from_analysis(_make_analysis(), specs)

        assert captions["telegram"] == "telegram-cap"
        assert sd == "sd-text"

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
        captions, sd, _usages = await ai.create_multi_caption_pair_from_analysis(_make_analysis(), specs)

        assert captions["telegram"] == "telegram-only"
        assert sd is None
