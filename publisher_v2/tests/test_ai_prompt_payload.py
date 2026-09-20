"""CAP-1/CAP-3/HYG-4 (#79): what actually reaches the OpenAI client.

The default config path (SD single-call enabled) must send the copywriter
system prompt, not the Stable-Diffusion prompt-engineer persona, and must
size temperature/max_tokens per platform mix instead of letting one short
platform (email, 240) throttle the whole multi-platform call.
"""

from __future__ import annotations

import json
import logging

import pytest

from publisher_v2.config.schema import OpenAIConfig
from publisher_v2.core.models import CaptionSpec, ImageAnalysis
from publisher_v2.services.ai import (
    DEFAULT_CAPTION_TEMPERATURE,
    SHORT_LIMIT_TEMPERATURE,
    AIService,
    CaptionGeneratorOpenAI,
)

# --- Fakes (same shape as test_ai_multi_caption.py) ---


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
        "telegram": CaptionSpec(platform="telegram", style="conversational", hashtags="#a", max_length=4096),
        "instagram": CaptionSpec(platform="instagram", style="hook-first", hashtags="#a", max_length=2200),
        "email": CaptionSpec(platform="email", style="engagement question", hashtags="", max_length=240),
    }


def _make_analysis() -> ImageAnalysis:
    return ImageAnalysis(description="Fine-art portrait", mood="calm", tags=["portrait"])


def _default_config() -> OpenAIConfig:
    return OpenAIConfig(
        api_key="sk-test",
        vision_model="gpt-4o",
        caption_model="gpt-4o-mini",
        sd_caption_enabled=True,
        sd_caption_single_call_enabled=True,
    )


def _sd_response() -> str:
    return json.dumps({"telegram": "t", "instagram": "i", "email": "e", "sd_caption": "sd prompt"})


def _make_generator(monkeypatch: pytest.MonkeyPatch, response: str) -> tuple[CaptionGeneratorOpenAI, _FakeCompletions]:
    completions = _FakeCompletions(response)
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _FakeClient(completions))
    return CaptionGeneratorOpenAI(_default_config()), completions


class TestDefaultSdMultiPathPersona:
    async def test_system_message_is_copywriter_not_prompt_engineer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gen, completions = _make_generator(monkeypatch, _sd_response())
        await gen.generate_multi_with_sd(_make_analysis(), _make_specs())

        assert len(completions.calls) == 1
        system_content = completions.calls[0]["messages"][0]["content"]
        # #82 replaced the generic "senior social media copywriter" system prompt with a
        # named voice brief (still the caption persona, not the SD prompt-engineer persona).
        # Assert against the actual configured personas rather than the exact wording so this
        # doesn't re-break every time the voice brief copy is tuned.
        assert system_content == gen.system_prompt
        assert system_content != gen.sd_caption_role_prompt
        assert "prompt engineer" not in system_content

    async def test_sd_caption_still_requested_in_user_prompt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gen, completions = _make_generator(monkeypatch, _sd_response())
        result, _usage = await gen.generate_multi_with_sd(_make_analysis(), _make_specs())

        user_content = completions.calls[0]["messages"][1]["content"]
        assert "sd_caption" in user_content
        assert result["sd_caption"] == "sd prompt"


class TestMultiCallBudgets:
    async def test_mixed_platforms_use_default_temperature_and_scaled_tokens(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gen, completions = _make_generator(monkeypatch, _sd_response())
        await gen.generate_multi_with_sd(_make_analysis(), _make_specs())

        call = completions.calls[0]
        assert call["temperature"] == DEFAULT_CAPTION_TEMPERATURE == 0.7
        assert call["max_tokens"] >= 1500
        assert call["max_tokens"] <= 4000
        assert call["presence_penalty"] == 0.6

    async def test_generate_multi_mixed_platforms_not_throttled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gen, completions = _make_generator(monkeypatch, json.dumps({"telegram": "t", "instagram": "i", "email": "e"}))
        await gen.generate_multi(_make_analysis(), _make_specs())

        call = completions.calls[0]
        assert call["temperature"] == DEFAULT_CAPTION_TEMPERATURE
        assert call["max_tokens"] >= 1500

    async def test_email_only_keeps_short_limit_regime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PUB-046 regression: an all-short call keeps the low-temperature regime
        and a small token cap."""
        gen, completions = _make_generator(monkeypatch, json.dumps({"email": "e", "sd_caption": "sd"}))
        email_only = {"email": CaptionSpec(platform="email", style="q", hashtags="", max_length=240)}
        await gen.generate_multi_with_sd(_make_analysis(), email_only)

        call = completions.calls[0]
        assert call["temperature"] == SHORT_LIMIT_TEMPERATURE
        assert call["max_tokens"] <= 512


class TestSdFallbackLogging:
    async def test_sd_failure_logged_and_single_fallback_call(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        calls = {"with_sd": 0, "multi": 0}

        class _StubGenerator:
            sd_caption_enabled = True
            sd_caption_single_call_enabled = True

            async def generate_multi_with_sd(self, analysis, specs, history=None, voice_examples=None):
                calls["with_sd"] += 1
                raise RuntimeError("boom")

            async def generate_multi(self, analysis, specs, history=None, voice_examples=None):
                calls["multi"] += 1
                return {name: "caption" for name in specs}, None

        service = AIService(analyzer=None, generator=_StubGenerator())  # type: ignore[arg-type]
        with caplog.at_level(logging.WARNING, logger="publisher_v2.services.ai"):
            captions, sd, _usages = await service.create_multi_caption_pair_from_analysis(
                _make_analysis(), _make_specs()
            )

        assert calls == {"with_sd": 1, "multi": 1}
        assert sd is None
        assert set(captions) == {"telegram", "instagram", "email"}
        events = [r for r in caplog.records if "sd_caption_path_failed" in r.getMessage()]
        assert len(events) == 1
        assert "RuntimeError" in events[0].getMessage()

    async def test_single_platform_sd_failure_logged(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        class _StubGenerator:
            sd_caption_enabled = True
            sd_caption_single_call_enabled = True

            async def generate_with_sd(self, analysis, spec):
                raise RuntimeError("boom")

            async def generate(self, analysis, spec):
                return "caption", None

        service = AIService(analyzer=None, generator=_StubGenerator())  # type: ignore[arg-type]
        spec = CaptionSpec(platform="telegram", style="s", hashtags="", max_length=4096)
        with caplog.at_level(logging.WARNING, logger="publisher_v2.services.ai"):
            caption, sd, _usages = await service.create_caption_pair_from_analysis(_make_analysis(), spec)

        assert caption == "caption"
        assert sd is None
        assert any("sd_caption_path_failed" in r.getMessage() for r in caplog.records)


async def test_service_path_sends_caption_persona_system_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """#135: through AIService.create_multi_caption_pair_from_analysis with the default config —
    the request that reaches the OpenAI client carries the caption persona, not the SD prompt engineer."""
    from publisher_v2.services.ai import VisionAnalyzerOpenAI

    completions = _FakeCompletions(_sd_response())
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _FakeClient(completions))
    cfg = _default_config()
    generator = CaptionGeneratorOpenAI(cfg)
    service = AIService(VisionAnalyzerOpenAI(cfg), generator)

    captions, sd_caption, _usages = await service.create_multi_caption_pair_from_analysis(
        _make_analysis(), _make_specs()
    )

    assert captions == {"telegram": "t", "instagram": "i", "email": "e"}
    assert sd_caption == "sd prompt"
    assert len(completions.calls) == 1
    messages = completions.calls[0]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == generator.system_prompt
    assert "prompt engineer" not in messages[0]["content"].lower()
    assert "sd_caption" in messages[1]["content"]


# ---------- #138: tenant-neutral default persona, fewer machine tells ----------


def _captured_user_prompt(monkeypatch: pytest.MonkeyPatch) -> tuple[CaptionGeneratorOpenAI, _FakeCompletions]:
    completions = _FakeCompletions(json.dumps({"telegram": "t", "email": "e", "sd_caption": "s"}))
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda **_kw: _FakeClient(completions))
    return CaptionGeneratorOpenAI(OpenAIConfig(api_key="sk-test")), completions


async def test_default_system_prompt_is_tenant_neutral_and_keeps_banned_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Asserted on the message that reaches the client, not on the attribute.

    Reading `gen.system_prompt` proves what was assembled, not what was sent —
    the two diverged once already (#135, the SD persona on the caption path).
    """
    gen, completions = _captured_user_prompt(monkeypatch)

    await _generate_through_the_service(gen, completions)

    system = completions.calls[-1]["messages"][0]["content"].lower()
    assert "banned" in system
    assert "rope" not in system
    assert "kink" not in system


async def _generate_through_the_service(gen: CaptionGeneratorOpenAI, completions: _FakeCompletions) -> str:
    """Drive AIService, not the generator, and return the user message sent."""
    from publisher_v2.services.ai import AIService, VisionAnalyzerOpenAI

    service = AIService(VisionAnalyzerOpenAI(OpenAIConfig(api_key="sk-test")), gen)
    specs = {
        "telegram": CaptionSpec(platform="telegram", style="conversational", hashtags="", max_length=4096),
        "email": CaptionSpec(platform="email", style="short", hashtags="", max_length=240),
    }
    await service.create_multi_caption_pair_from_analysis(ImageAnalysis(description="d", mood="m", tags=["t"]), specs)
    return str(completions.calls[-1]["messages"][-1]["content"])


async def test_user_prompt_has_no_machine_tells(monkeypatch: pytest.MonkeyPatch) -> None:
    gen, completions = _captured_user_prompt(monkeypatch)
    user = await _generate_through_the_service(gen, completions)
    assert "Write a caption for:" not in user
    assert "will be truncated" not in user.lower()
    # Hard limits live in one trailing Constraints line.
    assert user.count("Constraints:") == 1


def test_condense_pass_writes_as_the_same_writer() -> None:
    from publisher_v2.services.ai import CONDENSE_SYSTEM_PROMPT

    assert "same writer" in CONDENSE_SYSTEM_PROMPT
    assert "text editor" not in CONDENSE_SYSTEM_PROMPT
    # Injection hardening stays.
    assert "untrusted" in CONDENSE_SYSTEM_PROMPT


async def test_email_word_limit_reaches_the_real_prompt_and_matches_brief(monkeypatch: pytest.MonkeyPatch) -> None:
    """#138 review: the Constraints line carries each platform's limit and agrees with the 30-35 word brief."""
    gen, completions = _captured_user_prompt(monkeypatch)
    specs = {
        "telegram": CaptionSpec(platform="telegram", style="conversational", hashtags="", max_length=4096),
        "email": CaptionSpec(platform="email", style="short", hashtags="", max_length=240),
    }
    await gen.generate_multi_with_sd(ImageAnalysis(description="d", mood="m", tags=["t"]), specs)
    user = completions.calls[-1]["messages"][-1]["content"]
    assert "email at most 40 words (aim for 30-35)" in user
    assert "telegram at most 4096 characters" in user


def test_vision_completion_cap_fits_caption_facing_fields() -> None:
    from publisher_v2.services.ai import VisionAnalyzerOpenAI

    analyzer = VisionAnalyzerOpenAI(OpenAIConfig(api_key="sk-test"))
    assert analyzer.max_completion_tokens >= 1024


class TestATenantPersonaKeepsTheRules:
    """#138: a tenant system_prompt replaces the whole default persona.

    That is what the docs tell a tenant to set, so the banned-constructions
    rules — the part that delivers "fewer machine tells" — have to survive it.
    They live under their own YAML key and are appended to whichever persona is
    in force.
    """

    @staticmethod
    def _generator(monkeypatch: pytest.MonkeyPatch, system_prompt: str | None) -> CaptionGeneratorOpenAI:
        completions = _FakeCompletions(json.dumps({"telegram": "t", "email": "e", "sd_caption": "s"}))
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda **_kw: _FakeClient(completions))
        kwargs = {"api_key": "sk-test"}
        if system_prompt is not None:
            kwargs["system_prompt"] = system_prompt
        return CaptionGeneratorOpenAI(OpenAIConfig(**kwargs))

    def test_a_tenant_persona_still_carries_the_banned_list(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gen = self._generator(monkeypatch, "You write as a rope artist in Berlin. Terse, dry, first person.")

        assert "rope artist in Berlin" in gen.system_prompt
        assert "BANNED CONSTRUCTIONS" in gen.system_prompt
        assert "step into" in gen.system_prompt

    def test_the_default_persona_carries_them_once(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gen = self._generator(monkeypatch, None)

        assert gen.system_prompt.count("BANNED CONSTRUCTIONS") == 1

    async def test_a_single_platform_call_is_briefed_for_one_platform(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The fallbacks send one Platform= line, so "one caption per platform below" contradicted them."""
        completions = _FakeCompletions("a caption")
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda **_kw: _FakeClient(completions))
        gen = CaptionGeneratorOpenAI(OpenAIConfig(api_key="sk-test"))
        spec = CaptionSpec(platform="email", style="short", hashtags="", max_length=240)

        await gen.generate(ImageAnalysis(description="d", mood="m", tags=["t"]), spec)

        user = completions.calls[-1]["messages"][-1]["content"]
        assert "one caption per platform" not in user.lower()
        assert "one caption for the platform" in user.lower()
        assert user.count("Platform=") == 1


def test_a_null_sensory_detail_does_not_become_the_word_none() -> None:
    """The model returns null for a field it cannot fill; str(None) is "None"."""
    from publisher_v2.services.ai import _as_detail_list

    assert _as_detail_list([None, "warm jute", None]) == ["warm jute"]
    assert _as_detail_list(None) == []
    assert _as_detail_list([None, None]) == []


class TestTheBudgetAndTheBriefAreRespected:
    """#138 follow-ups: behaviours the fixes claimed but nothing asserted."""

    @staticmethod
    def _specs_with_examples(examples: tuple[str, ...]) -> dict[str, CaptionSpec]:
        return {
            "telegram": CaptionSpec(
                platform="telegram", style="conversational", hashtags="", max_length=4096, examples=examples
            ),
            "email": CaptionSpec(platform="email", style="short", hashtags="", max_length=240, examples=examples),
        }

    def test_an_empty_voice_list_is_a_decision_not_an_absence(self) -> None:
        """truncate_voice_profile_to_budget returns [] when the first example busts the budget.

        Promoting the specs' own copies then would put the untruncated profile
        straight back into the prompt, defeating PUB-029's budget.
        """
        from publisher_v2.services.ai import CaptionGeneratorOpenAI

        specs = self._specs_with_examples(("A very long voice example that blew the budget.",))

        prompt, _keys = CaptionGeneratorOpenAI._build_multi_prompt(
            "Write captions.",
            ImageAnalysis(description="d", mood="m", tags=["t"]),
            specs,
            None,
            voice_examples=[],
        )

        assert "blew the budget" not in prompt
        assert "STYLE REFERENCES" not in prompt

    def test_no_voice_list_still_promotes_the_specs_examples(self) -> None:
        from publisher_v2.services.ai import CaptionGeneratorOpenAI

        specs = self._specs_with_examples(("My signature line.",))

        prompt, _keys = CaptionGeneratorOpenAI._build_multi_prompt(
            "Write captions.",
            ImageAnalysis(description="d", mood="m", tags=["t"]),
            specs,
            None,
        )

        assert prompt.count("My signature line.") == 1

    async def test_a_tenant_role_prompt_survives_on_the_single_platform_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The single-platform brief must not silently override a tenant's own role."""
        completions = _FakeCompletions("a caption")
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda **_kw: _FakeClient(completions))
        gen = CaptionGeneratorOpenAI(OpenAIConfig(api_key="sk-test", role_prompt="My own brief, thanks."))

        await gen.generate(
            ImageAnalysis(description="d", mood="m", tags=["t"]),
            CaptionSpec(platform="email", style="short", hashtags="", max_length=240),
        )

        user = completions.calls[-1]["messages"][-1]["content"]
        assert user.startswith("My own brief, thanks.")

    def test_a_mandated_closing_is_stated_in_the_block(self) -> None:
        from publisher_v2.services.ai import build_platform_block

        spec = CaptionSpec(platform="email", style="short", hashtags="", max_length=240, closing="statement")

        block = build_platform_block(1, "email", spec)

        assert "end with a statement" in block.lower()
