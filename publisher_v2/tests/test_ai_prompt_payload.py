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


def _platform_response() -> str:
    # PUB-051 AC4: the caption completion returns platform keys only.
    return json.dumps({"telegram": "t", "instagram": "i", "email": "e"})


def _make_generator(monkeypatch: pytest.MonkeyPatch, response: str) -> tuple[CaptionGeneratorOpenAI, _FakeCompletions]:
    completions = _FakeCompletions(response)
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _FakeClient(completions))
    return CaptionGeneratorOpenAI(_default_config()), completions


class TestDefaultSdMultiPathPersona:
    # PUB-051 AC4: the caption-stage completion no longer carries sd_caption, so these
    # drive generate_multi (platform keys only). The old
    # test_sd_caption_still_requested_in_user_prompt asserted the behaviour AC4 removes
    # (sd_caption requested by the caption completion); it is replaced by
    # test_ai_multi_caption.py::test_caption_call_requests_platform_keys_only_no_sd_caption.
    async def test_system_message_is_copywriter_not_prompt_engineer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gen, completions = _make_generator(monkeypatch, _platform_response())
        await gen.generate_multi(_make_analysis(), _make_specs())

        assert len(completions.calls) == 1
        system_content = completions.calls[0]["messages"][0]["content"]
        # #82 replaced the generic "senior social media copywriter" system prompt with a
        # named voice brief (still the caption persona, not the SD prompt-engineer persona).
        # Assert against the actual configured personas rather than the exact wording so this
        # doesn't re-break every time the voice brief copy is tuned.
        assert system_content == gen.system_prompt
        assert "prompt engineer" not in system_content


class TestMultiCallBudgets:
    async def test_mixed_platforms_use_default_temperature_and_scaled_tokens(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gen, completions = _make_generator(monkeypatch, _platform_response())
        await gen.generate_multi(_make_analysis(), _make_specs())

        call = completions.calls[0]
        # PUB-051 Scope: caption sampling is temperature 0.9 / frequency 0.3 / presence 0.6
        # (was 0.7 with no frequency penalty).
        assert call["temperature"] == DEFAULT_CAPTION_TEMPERATURE == 0.9
        assert call["max_tokens"] >= 1500
        assert call["max_tokens"] <= 4000
        assert call["presence_penalty"] == 0.6
        assert call["frequency_penalty"] == 0.3

    async def test_generate_multi_mixed_platforms_not_throttled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        gen, completions = _make_generator(monkeypatch, json.dumps({"telegram": "t", "instagram": "i", "email": "e"}))
        await gen.generate_multi(_make_analysis(), _make_specs())

        call = completions.calls[0]
        assert call["temperature"] == DEFAULT_CAPTION_TEMPERATURE
        assert call["max_tokens"] >= 1500

    async def test_email_only_keeps_short_limit_regime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """PUB-046 regression: an all-short call keeps the low-temperature regime
        and a small token cap."""
        gen, completions = _make_generator(monkeypatch, json.dumps({"email": "e"}))
        email_only = {"email": CaptionSpec(platform="email", style="q", hashtags="", max_length=240)}
        await gen.generate_multi(_make_analysis(), email_only)

        call = completions.calls[0]
        assert call["temperature"] == SHORT_LIMIT_TEMPERATURE
        assert call["max_tokens"] <= 512


class TestSdFallbackLogging:
    # PUB-051 AC4/AC5: the multi-platform caption path no longer has an sd_caption
    # completion to fail over from (sd_caption comes from the vision stage), so the old
    # test_sd_failure_logged_and_single_fallback_call — which asserted the multi path
    # tries generate_multi_with_sd first and then pays for generate_multi — is removed.
    # The single-platform fallback (generate_with_sd) keeps its SD pass and its test.
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

    completions = _FakeCompletions(_platform_response())
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key, **kwargs: _FakeClient(completions))
    cfg = _default_config()
    generator = CaptionGeneratorOpenAI(cfg)
    service = AIService(VisionAnalyzerOpenAI(cfg), generator)

    # PUB-051: the return gained the per-platform angles as a fourth element.
    captions, sd_caption, _usages, _angles = await service.create_multi_caption_pair_from_analysis(
        _make_analysis(), _make_specs()
    )

    assert captions == {"telegram": "t", "instagram": "i", "email": "e"}
    # PUB-051 AC4: the caption completion no longer produces (or requests) sd_caption.
    assert sd_caption is None
    assert len(completions.calls) == 1
    messages = completions.calls[0]["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == generator.system_prompt
    assert "prompt engineer" not in messages[0]["content"].lower()
    assert "sd_caption" not in messages[1]["content"]


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
    # PUB-051 AC4: generate_multi is the caption-stage multi call (no sd_caption variant).
    await gen.generate_multi(ImageAnalysis(description="d", mood="m", tags=["t"]), specs)
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


# ---------- PUB-051 AC2/AC3: no closing-pattern line, two openings, a sub-500-token prompt ----------


def _pub051_specs() -> dict[str, CaptionSpec]:
    """The shipped telegram/instagram/email specs (real registry, real briefs)."""
    from caption_pipeline_fakes import pipeline_config

    return CaptionSpec.for_platforms(pipeline_config(telegram=True, instagram=True, email=True))


# 20 snake_case tags: the 15-25 range the vision prompt asks for (#177 M3).
_PUB051_TAGS = [
    "rope_art",
    "negative_space",
    "jute_harness",
    "window_light",
    "kneeling_pose",
    "fine_art_nude",
    "shibari_study",
    "hard_shadow",
    "wooden_floor",
    "bare_wall",
    "figure_study",
    "natural_fibre",
    "low_key",
    "side_light",
    "body_form",
    "texture_contrast",
    "monochrome_palette",
    "quiet_mood",
    "studio_session",
    "knot_detail",
]


def _pub051_analysis() -> ImageAnalysis:
    """A full vision result: every metadata field, hex palette, 20 snake_case tags, caption-facing fields."""
    from caption_pipeline_fakes import MOOD_NOTE, SENSORY_DETAIL, VISION_NEUTRAL

    fields = dict(VISION_NEUTRAL)
    fields["tags"] = list(_PUB051_TAGS)
    return ImageAnalysis(**fields, sensory_detail=list(SENSORY_DETAIL), mood_note=MOOD_NOTE)


# Six owner-voice examples of realistic length (the "six-example profile").
_PUB051_VOICE = [
    "Two hours on the floor and the tea went cold. Worth it.",
    "She laughed at the third knot. I retied it anyway.",
    "Jute smells like a barn in August. I have stopped apologising for that.",
    "Window light does half the work. I just stay out of its way.",
    "Nobody talks during the last wrap. That is the whole point of it.",
    "Rain on the skylight, a slow tie, nowhere else to be tonight.",
]


def _pub051_history(platforms: list[str], per_platform: int = 8) -> dict[str, list[str]]:
    """Realistic per-platform history, most-recent-first. Each caption opens with a unique token."""
    bodies = [
        "the rope went on before the kettle boiled and nobody said a word for a while.",
        "a frayed end left untrimmed, because the knot deserves its own record. #shibari",
        "window light, a bare wall, and the patience it takes to tie something well 🌿",
        "the second wrap took longer than the first; neither of us minded the wait.",
        "hemp smells like a hardware shop and that has never bothered anyone here.",
        "we stopped twice, which was the point of the whole afternoon, honestly.",
        "cold floorboards, warm hands, and a harness that finally sat right tonight.",
        "half the knots came undone on their own and we laughed about it after.",
    ]
    return {p: [f"{_opening_token(p, i)} {bodies[i % len(bodies)]}" for i in range(per_platform)] for p in platforms}


def _opening_token(platform: str, index: int) -> str:
    return f"Zq{platform[:3].capitalize()}{index}x"


async def _pub051_prompts(
    monkeypatch: pytest.MonkeyPatch,
    specs: dict[str, CaptionSpec],
    history: dict[str, list[str]] | list[str] | None,
    voice_examples: list[str] | None = None,
    analysis: ImageAnalysis | None = None,
) -> list[str]:
    """Drive the real AIService against a recording fake client; return every caption user message."""
    from caption_pipeline_fakes import FakeOpenAI, install_fake_openai, real_ai_service, user_text

    fake = FakeOpenAI(list(specs))
    install_fake_openai(monkeypatch, fake)
    await real_ai_service().create_multi_caption_pair_from_analysis(
        analysis or _pub051_analysis(), specs, history=history, voice_examples=voice_examples
    )
    return [user_text(c) for c in fake.caption_calls]


async def test_no_closing_pattern_line_is_ever_rendered(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2: no closing-pattern constraint anywhere — per-platform or flat history, any `closing` setting."""
    specs = _pub051_specs()
    assert specs["email"].closing == "any", "the shipped email brief is the case that always emitted the line"
    mandated = {
        "telegram": CaptionSpec(platform="telegram", style="s", hashtags="", max_length=4096, closing="statement"),
        "email": CaptionSpec(platform="email", style="s", hashtags="", max_length=240, closing="question"),
    }
    scenarios: list[tuple[dict[str, CaptionSpec], dict[str, list[str]] | list[str]]] = [
        (specs, _pub051_history(list(specs))),
        (specs, _pub051_history(["email"])["email"]),  # legacy flat list
        (mandated, _pub051_history(list(mandated))),
    ]

    prompts: list[str] = []
    for scenario_specs, history in scenarios:
        prompts += await _pub051_prompts(monkeypatch, scenario_specs, history)

    assert prompts
    for prompt in prompts:
        lowered = prompt.lower()
        assert "closing pattern" not in lowered, prompt
        offending = [line for line in lowered.splitlines() if "closing" in line and "avoid" in line]
        assert offending == [], offending


async def test_at_most_two_openings_to_avoid_appear_per_platform(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC2: the rendered avoid-list is capped at the two most recent, however much history was fetched."""
    specs = _pub051_specs()
    history = _pub051_history(list(specs), per_platform=8)

    (prompt,) = await _pub051_prompts(monkeypatch, specs, history)

    for platform in specs:
        present = [i for i in range(8) if _opening_token(platform, i) in prompt]
        assert len(present) <= 2, f"{platform}: {len(present)} openings rendered ({present})"
        assert set(present) <= {0, 1}, f"{platform}: rendered openings are not the two most recent ({present})"
        assert 0 in present, f"{platform}: the most recent opening is no longer avoided"

    # The legacy flat-history block is capped the same way.
    flat = history["email"]
    (flat_prompt,) = await _pub051_prompts(monkeypatch, specs, flat)
    assert sum(_opening_token("email", i) in flat_prompt for i in range(8)) <= 2


async def test_user_message_under_500_tokens_with_history_and_six_examples(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC3: with 8-deep history on three platforms, a six-example profile and a full analysis.

    Measured exactly as the spec pins it: ``len(prompt) / 4`` (no tokenizer dependency).
    """
    specs = _pub051_specs()
    assert len(_PUB051_VOICE) == 6

    (prompt,) = await _pub051_prompts(
        monkeypatch, specs, _pub051_history(list(specs), per_platform=8), voice_examples=list(_PUB051_VOICE)
    )

    # The examples really are in there — the bound is not met by dropping the profile.
    assert all(example in prompt for example in _PUB051_VOICE)
    assert len(prompt) / 4 < 500, f"user message is {len(prompt) / 4:.0f} tokens (len/4)"


async def test_analysis_prose_contains_no_hex_colour_or_snake_case_tag(monkeypatch: pytest.MonkeyPatch) -> None:
    """AC3 + Scope: analysis rendered as prose; color_palette, tags and aesthetic_terms dropped."""
    import re

    specs = _pub051_specs()
    analysis = _pub051_analysis()

    (prompt,) = await _pub051_prompts(monkeypatch, specs, _pub051_history(list(specs)), analysis=analysis)

    assert not re.search(r"#[0-9a-fA-F]{6}\b", prompt), "a hex colour reached the caption prompt"
    leaked_tags = [t for t in analysis.tags if t in prompt]
    assert leaked_tags == [], f"snake_case tags reached the caption prompt: {leaked_tags}"
    leaked_terms = [t for t in analysis.aesthetic_terms if t in prompt]
    assert leaked_terms == [], f"aesthetic_terms reached the caption prompt: {leaked_terms}"
    # Prose, not a Python repr of a list or a key='value' dump.
    assert "['" not in prompt
    assert not re.search(r"\b[a-z]+(?:_[a-z]+)+='", prompt), "analysis rendered as key='value' pairs"


def test_caption_rules_cover_every_tells_lexicon_pattern() -> None:
    """PUB-051 AC2 regression guard: every tells pattern has a corresponding rules line.

    ``utils.caption_metrics.DEFAULT_TELLS_LEXICON`` is the source of truth for what
    counts as a machine tell (the YAML comment says so). Each pattern needs a
    "write X instead of Y" line in ``caption.rules`` that names the tell in a form
    the pattern itself matches, so the two cannot drift apart unnoticed.

    ``caption.rules`` is a folded YAML scalar, so it loads as one physical line;
    its lines are the ``;``-separated entries, and a match must fall inside one.
    The pattern is applied exactly as the metric applies it (``re.IGNORECASE``).
    """
    import re

    from publisher_v2.config.static_loader import get_static_config
    from publisher_v2.utils.caption_metrics import DEFAULT_TELLS_LEXICON

    rules = get_static_config().ai_prompts.caption.rules
    assert rules
    rule_lines = [line.strip() for line in re.split(r"[;\n]", rules) if line.strip()]

    uncovered = [
        pattern
        for pattern in DEFAULT_TELLS_LEXICON
        if not any(re.search(pattern, line, re.IGNORECASE) for line in rule_lines)
    ]
    assert uncovered == [], f"tells with no matching caption.rules line: {uncovered}"


# ---------- PUB-051 critique follow-up: smart-hashtag topics, AC3 headroom ----------


def _platform_blocks(prompt: str, platforms: list[str]) -> dict[str, str]:
    """Each platform's block: its numbered ``N. <platform>:`` line plus the indented lines under it."""
    import re

    blocks: dict[str, str] = {}
    current: str | None = None
    for line in prompt.splitlines():
        head = re.match(r"^\d+\.\s+(\w+):", line)
        if head and head.group(1) in platforms:
            current = head.group(1)
            blocks[current] = line
        elif current is not None and line.startswith((" ", "\t")) and line.strip():
            blocks[current] += "\n" + line
        else:
            current = None
    return blocks


async def test_smart_hashtag_platform_gets_plain_word_topics_from_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    """A smart-hashtags platform's block carries up to 5 topics from ``analysis.tags``, as plain spaced words.

    Platforms without smart hashtags get no topics; no snake_case tag reaches the prompt anywhere.
    """
    import dataclasses

    specs = _pub051_specs()
    specs["instagram"] = dataclasses.replace(specs["instagram"], smart_hashtags=True)
    assert not specs["telegram"].smart_hashtags and not specs["email"].smart_hashtags
    analysis = _pub051_analysis()
    topics = [t.replace("_", " ") for t in analysis.tags]

    (prompt,) = await _pub051_prompts(monkeypatch, specs, _pub051_history(list(specs)), analysis=analysis)

    blocks = _platform_blocks(prompt, list(specs))
    assert set(blocks) == set(specs), f"could not find every platform block: {sorted(blocks)}"
    offered = [t for t in topics if t in blocks["instagram"]]
    assert 1 <= len(offered) <= 5, f"instagram should get 1-5 hashtag topics from the tags, got {offered}"
    for platform in ("telegram", "email"):
        leaked = [t for t in topics if t in blocks[platform]]
        assert leaked == [], f"{platform} has no smart hashtags but got topics {leaked}"
    snake = [t for t in analysis.tags if t in prompt]
    assert snake == [], f"snake_case tags reached the prompt: {snake}"


# Six owner-voice examples at the realistic upper range (~120 characters each).
_PUB051_LONG_VOICE = [
    "Two hours on the studio floor and the tea went cold beside us. Neither of us noticed until the last knot came off.",
    "She laughed at the third knot because it sat crooked on her hip. I retied it anyway, slower this time, and she stopped.",
    "Jute smells like a barn in late August and the whole room takes it on. I have stopped apologising to anyone for that.",
    "Window light does half the work on a grey afternoon. I mostly try to stay out of its way and keep my hands steady.",
    "Nobody talks during the last wrap; the room goes quiet on its own. That silence is the part I keep coming back for.",
    "Rain on the skylight all evening, a slow tie on the wooden floor, and nowhere else either of us needed to be tonight.",
]

_PUB051_SEED_HASHTAGS = "#shibari #ropeart #jute #fineart #kinbaku"


async def test_heavy_tenant_user_message_stays_under_600_tokens(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard on prompt growth for heavy tenants.

    The AC3 fixture plus instagram smart hashtags with ~5 seed tags and six ~120-char examples.
    Measured exactly as the spec pins it: ``len(prompt) / 4``.

    The spec's 500-token bound is pinned by the original AC3 test on the spec's own fixture
    (history and a six-example profile). This heavier fixture measured ~570 (569.5) at
    implementation; reaching 500 here would require cutting the analysis prose or the AC2
    openings. That gap is reported to the owner as a spec question; until it is answered this
    test only guards against further growth.
    """
    import dataclasses

    specs = _pub051_specs()
    specs["instagram"] = dataclasses.replace(specs["instagram"], smart_hashtags=True, hashtags=_PUB051_SEED_HASHTAGS)
    assert len(_PUB051_LONG_VOICE) == 6
    assert all(100 <= len(e) <= 125 for e in _PUB051_LONG_VOICE), [len(e) for e in _PUB051_LONG_VOICE]

    (prompt,) = await _pub051_prompts(
        monkeypatch, specs, _pub051_history(list(specs), per_platform=8), voice_examples=list(_PUB051_LONG_VOICE)
    )

    # The bound must not be met by dropping the profile or the seed tags.
    assert all(example in prompt for example in _PUB051_LONG_VOICE)
    assert all(tag in prompt for tag in _PUB051_SEED_HASHTAGS.split())
    assert len(prompt) / 4 < 600, f"user message is {len(prompt) / 4:.0f} tokens (len/4)"
