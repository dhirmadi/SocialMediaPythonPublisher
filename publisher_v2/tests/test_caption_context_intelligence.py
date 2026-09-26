"""Tests for PUB-035: Caption Context Intelligence.

Covers all four parts:
  A — Style examples in platform registry
  B — Trend guidance per platform
  C — Caption history as sliding context window
  D — Operator edit tracking in sidecars
"""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

import pytest

from publisher_v2.config.static_loader import PlatformCaptionStyle
from publisher_v2.core.models import CaptionSpec

# ---------------------------------------------------------------------------
# Part A: Style examples
# ---------------------------------------------------------------------------


class TestStyleExamples:
    """#138 (replaces AC1): no static example captions ship; PlatformCaptionStyle has no examples.

    The tenant voice_profile (carried on CaptionSpec.examples) is the only source
    of examples, so the static style model rejects an ``examples`` key outright.
    """

    def test_style_has_no_examples_field(self) -> None:
        assert "examples" not in PlatformCaptionStyle.model_fields

    def test_examples_list_is_stripped_and_logged(self, caplog) -> None:
        """#138: dropped, not rejected.

        PV2_STATIC_CONFIG_DIR is a fleet-wide override, so raising here took
        every instance down — the CLI at generator construction and the web app
        inside its lifespan, so even `GET /` 500s — for a key whose contents
        never reach a prompt anyway.
        """
        import logging

        caplog.set_level(logging.WARNING, logger="publisher_v2.config.static")

        style = PlatformCaptionStyle(style="s", examples=["Example one", "Example two"])  # type: ignore[call-arg]

        assert style.style == "s"
        assert not hasattr(style, "examples")
        assert any("static_caption_examples_ignored" in r.getMessage() for r in caplog.records), caplog.text

    def test_style_roundtrip_keeps_closing(self) -> None:
        style = PlatformCaptionStyle(style="conversational", max_length=4096, hashtags=True, closing="statement")
        rebuilt = PlatformCaptionStyle(**style.model_dump())
        assert rebuilt.closing == "statement"
        assert rebuilt == style


class TestExamplesInPrompt:
    """AC2, as amended by #138: the examples appear once, in the hardened block.

    They used to be repeated inside every platform block as well, so with four
    platforms one example stood in front of the model four times over — which is
    how a "reference, do not copy" turns into a template.
    """

    _SPEC = CaptionSpec(
        platform="telegram",
        style="conversational",
        hashtags="#art",
        max_length=4096,
        examples=("The way light catches jute", "New work. Three hours of tying"),
        guidance="",
    )

    def test_the_platform_block_no_longer_repeats_them(self) -> None:
        from publisher_v2.services.ai import build_platform_block

        block = build_platform_block(1, "telegram", self._SPEC)

        assert "Voice examples" not in block
        assert "The way light catches jute" not in block

    def test_the_assembled_prompt_carries_each_example_once(self) -> None:
        import dataclasses

        from publisher_v2.core.models import ImageAnalysis
        from publisher_v2.services.ai import CaptionGeneratorOpenAI

        specs = {
            "telegram": self._SPEC,
            "email": dataclasses.replace(self._SPEC, platform="email"),
        }
        prompt, _keys = CaptionGeneratorOpenAI._build_multi_prompt(
            "Write captions.",
            ImageAnalysis(description="d", mood="m", tags=["t"]),
            specs,
            None,
            voice_examples=list(self._SPEC.examples),
        )

        assert prompt.count("The way light catches jute") == 1, prompt
        assert "STYLE REFERENCES" in prompt

    def test_prompt_omits_examples_when_empty(self) -> None:
        from publisher_v2.services.ai import build_platform_block

        spec = CaptionSpec(
            platform="telegram", style="conversational", hashtags="#art", max_length=4096, examples=(), guidance=""
        )
        block = build_platform_block(1, "telegram", spec)
        assert "Voice examples" not in block


# ---------------------------------------------------------------------------
# Part B: Trend guidance
# ---------------------------------------------------------------------------


class TestTrendGuidance:
    """AC3/AC4: PlatformCaptionStyle supports an optional guidance string."""

    def test_guidance_default_empty(self) -> None:
        style = PlatformCaptionStyle()
        assert style.guidance == ""

    def test_guidance_accepts_string(self) -> None:
        style = PlatformCaptionStyle(guidance="2026 Telegram art channels prefer short captions.")
        assert "2026 Telegram" in style.guidance

    def test_prompt_includes_guidance(self) -> None:
        from publisher_v2.services.ai import build_platform_block

        spec = CaptionSpec(
            platform="telegram",
            style="conversational",
            hashtags="#art",
            max_length=4096,
            examples=(),
            guidance="Short captions preferred in 2026.",
        )
        block = build_platform_block(1, "telegram", spec)
        assert "Guidance" in block
        assert "Short captions preferred in 2026." in block

    def test_prompt_omits_guidance_when_empty(self) -> None:
        from publisher_v2.services.ai import build_platform_block

        spec = CaptionSpec(
            platform="telegram", style="conversational", hashtags="#art", max_length=4096, examples=(), guidance=""
        )
        block = build_platform_block(1, "telegram", spec)
        assert "Guidance" not in block


# ---------------------------------------------------------------------------
# Part C: Caption history
# ---------------------------------------------------------------------------


class TestCaptionHistoryConfig:
    """AC5: Configurable caption_history.window_size."""

    def test_caption_history_defaults(self) -> None:
        from publisher_v2.config.static_loader import CaptionHistoryConfig

        cfg = CaptionHistoryConfig()
        # #82: window reduced from 8 to 3 — few-shot of the model's own
        # output anchors style; a small window keeps constraints, not examples.
        assert cfg.window_size == 3
        assert cfg.max_tokens_budget == 1000

    def test_caption_history_custom(self) -> None:
        from publisher_v2.config.static_loader import CaptionHistoryConfig

        cfg = CaptionHistoryConfig(window_size=5, max_tokens_budget=500)
        assert cfg.window_size == 5
        assert cfg.max_tokens_budget == 500


class TestCaptionHistoryPrompt:
    """AC6/AC8: History is injected into prompt with anti-repetition instructions."""

    def test_build_history_block_with_captions(self) -> None:
        # #82: history is rendered as constraints (openings/closings to avoid),
        # never as full quoted captions that anchor the model's style.
        from publisher_v2.services.ai import build_history_block

        captions = [
            "Caption one about quiet mornings in the studio today",
            "Did you notice the second one at all here?",
        ]
        block = build_history_block(captions)
        assert "openings to avoid" in block.lower()
        # PUB-051 AC2: the closing-pattern constraint is deleted (was: asserted present).
        assert "closing pattern" not in block.lower()
        for full in captions:
            assert full not in block

    def test_build_history_block_empty(self) -> None:
        from publisher_v2.services.ai import build_history_block

        assert build_history_block([]) == ""


class TestTokenBudget:
    """AC11: History context does not exceed max_tokens_budget."""

    def test_truncate_history_by_token_budget(self) -> None:
        from publisher_v2.services.ai import truncate_history_to_budget

        # Each caption ~10 tokens (~40 chars). Budget of 30 tokens should fit ~3.
        captions = [f"Caption number {i} with some words here." for i in range(10)]
        result = truncate_history_to_budget(captions, max_tokens_budget=30)
        assert len(result) <= 4  # tightened from < 10
        assert result[-1] == captions[-1]

    def test_budget_zero_returns_empty(self) -> None:
        from publisher_v2.services.ai import truncate_history_to_budget

        result = truncate_history_to_budget(["A caption"], max_tokens_budget=0)
        assert result == []


class TestSidecarEditTracking:
    """AC9: Sidecar stores caption_generated alongside caption when edited."""

    def test_sidecar_includes_caption_generated(self) -> None:
        from publisher_v2.utils.captions import build_caption_sidecar

        meta = {"image_file": "test.jpg", "caption_generated": "AI original caption", "caption_edited": True}
        content = build_caption_sidecar("Published caption", meta)
        assert "caption_generated: AI original caption" in content
        assert "caption_edited: True" in content

    def test_sidecar_omits_caption_generated_when_not_edited(self) -> None:
        from publisher_v2.utils.captions import build_caption_sidecar

        meta = {"image_file": "test.jpg", "caption_generated": None}
        content = build_caption_sidecar("AI caption", meta)
        assert "caption_generated" not in content

    def test_sidecar_service_accepts_edit_params(self) -> None:
        """generate_and_upload_sidecar accepts caption_generated and caption_edited params."""
        import inspect

        from publisher_v2.services.sidecar import generate_and_upload_sidecar

        sig = inspect.signature(generate_and_upload_sidecar)
        assert "caption_generated" in sig.parameters
        assert "caption_edited" in sig.parameters


# ---------------------------------------------------------------------------
# CaptionSpec extension
# ---------------------------------------------------------------------------


class TestCaptionSpecExtended:
    """CaptionSpec carries examples and guidance fields."""

    def test_caption_spec_has_examples(self) -> None:
        spec = CaptionSpec(
            platform="telegram",
            style="conversational",
            hashtags="#art",
            max_length=4096,
            examples=("Example one",),
            guidance="Be concise.",
        )
        assert spec.examples == ("Example one",)
        assert spec.guidance == "Be concise."

    def test_caption_spec_defaults(self) -> None:
        spec = CaptionSpec(platform="telegram", style="conversational", hashtags="#art", max_length=4096)
        assert spec.examples == ()
        assert spec.guidance == ""


# ---------------------------------------------------------------------------
# Integration: history flows through to prompt
# ---------------------------------------------------------------------------


class TestHistoryIntegration:
    """H4: Verify history actually reaches the LLM prompt via generate_multi."""

    async def test_generate_multi_includes_history_in_prompt(self) -> None:
        """When history is passed to generate_multi, the prompt includes it."""
        from publisher_v2.config.schema import OpenAIConfig
        from publisher_v2.core.models import ImageAnalysis
        from publisher_v2.services.ai import CaptionGeneratorOpenAI

        # Capture the prompt sent to OpenAI
        captured_prompts: list[str] = []

        class _Msg:
            content = '{"telegram": "test caption"}'

        class _Choice:
            message = _Msg()

        class _Resp:
            choices = [_Choice()]

        class _FakeCompletions:
            async def create(self, **kwargs: Any) -> _Resp:
                messages = kwargs.get("messages", [])
                for m in messages:  # type: ignore[union-attr]
                    if isinstance(m, dict) and m.get("role") == "user":
                        captured_prompts.append(m["content"])
                return _Resp()

        class _FakeClient:
            chat = type("C", (), {"completions": _FakeCompletions()})()

        config = OpenAIConfig(api_key="sk-test", caption_model="gpt-4o-mini")
        gen = CaptionGeneratorOpenAI(config)
        gen.client = _FakeClient()  # type: ignore[assignment]

        analysis = ImageAnalysis(description="test", mood="calm", tags=["art"])
        specs = {"telegram": CaptionSpec(platform="telegram", style="test", hashtags="", max_length=4096)}
        history = [
            "Previous caption one about the quiet light in the studio",
            "Previous caption two asking what you would notice first?",
        ]

        await gen.generate_multi(analysis, specs, history=history)

        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        # #82: history renders as constraints (openings/closings), never as
        # full quoted captions that anchor the model's style.
        assert "openings to avoid" in prompt.lower()
        for full in history:
            assert full not in prompt
        assert "Previous caption one about the quiet" in prompt
        assert "Previous caption two asking what you" in prompt


# ---------------------------------------------------------------------------
# Part D Extended: update_sidecar_with_caption for caption override
# ---------------------------------------------------------------------------


class TestUpdateSidecarWithCaption:
    """Test update_sidecar_with_caption for PUB-035 caption override fix."""

    @pytest.mark.asyncio
    async def test_updates_existing_sidecar_with_caption(self) -> None:
        """When a sidecar exists, update it with the published caption."""
        from publisher_v2.services.sidecar import update_sidecar_with_caption
        from publisher_v2.utils.captions import build_caption_sidecar
        from publisher_v2.web.sidecar_parser import parse_sidecar_text

        existing_sidecar = build_caption_sidecar(
            "Original SD caption",
            {"image_file": "test.jpg", "mood": "calm"},
        )

        class MockStorage:
            written_content: str | None = None

            async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None:
                return existing_sidecar.encode("utf-8")

            async def write_sidecar_text(self, folder: str, filename: str, content: str) -> None:
                self.written_content = content

        storage = MockStorage()
        await update_sidecar_with_caption(
            storage=storage,  # type: ignore[arg-type]
            folder="/images",
            filename="test.jpg",
            published_caption="My custom caption override",
            caption_edited=True,
        )

        assert storage.written_content is not None
        sd_caption, meta = parse_sidecar_text(storage.written_content)
        assert sd_caption == "Original SD caption"
        assert meta is not None
        assert meta["caption"] == "My custom caption override"
        assert meta["caption_edited"] == "True"
        assert "caption_updated_at" in meta
        assert meta["mood"] == "calm"

    @pytest.mark.asyncio
    async def test_creates_minimal_sidecar_when_none_exists(self) -> None:
        """When no sidecar exists, create a minimal one with the caption."""
        from publisher_v2.services.sidecar import update_sidecar_with_caption
        from publisher_v2.web.sidecar_parser import parse_sidecar_text

        class MockStorage:
            written_content: str | None = None

            async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None:
                return None

            async def write_sidecar_text(self, folder: str, filename: str, content: str) -> None:
                self.written_content = content

        storage = MockStorage()
        await update_sidecar_with_caption(
            storage=storage,  # type: ignore[arg-type]
            folder="/images",
            filename="test.jpg",
            published_caption="My manual caption",
            caption_edited=True,
        )

        assert storage.written_content is not None
        sd_caption, meta = parse_sidecar_text(storage.written_content)
        assert sd_caption == "My manual caption"
        assert meta is not None
        assert meta["caption"] == "My manual caption"
        assert meta["caption_edited"] == "True"


class TestHistoryAsConstraints:
    """#82: no full historical caption is ever quoted into a prompt."""

    def test_platform_block_renders_openings_not_full_captions(self) -> None:
        from publisher_v2.core.models import CaptionSpec
        from publisher_v2.services.ai import build_platform_block

        spec = CaptionSpec(platform="email", style="s", hashtags="", max_length=240)
        history = [
            "Soft rope steady hands and a gaze that does not flinch tonight",
            "Did you see how the light wraps around the second knot there?",
        ]
        block = build_platform_block(1, "email", spec, platform_history=history)
        assert "openings to avoid" in block.lower()
        # PUB-051 AC2: the closing-pattern constraint is deleted (was: asserted present).
        assert "closing pattern" not in block.lower()
        for full in history:
            assert full not in block
        # The opening of each (of the two most recent) captions is present as the avoid-list.
        assert "Soft rope steady hands and a" in block
        assert "Did you see how the light" in block

    # PUB-051 AC1: test_platform_block_includes_structure_directive asserted the
    # "Structure directive:" line, which the content angle replaces; superseded by
    # test_caption_angle_rotation.py::test_each_platform_receives_exactly_one_angle_per_call.


# ---------------------------------------------------------------------------
# #138: email prompt consistency, one directive per platform, no static examples
# ---------------------------------------------------------------------------


def _real_specs(**platforms: bool) -> dict[str, CaptionSpec]:
    from publisher_v2.config.schema import (
        ApplicationConfig,
        ContentConfig,
        DropboxConfig,
        OpenAIConfig,
        PlatformsConfig,
        StoragePathConfig,
    )

    cfg = ApplicationConfig(
        dropbox=DropboxConfig(app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos"),
        storage_paths=StoragePathConfig(image_folder="/Photos"),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(
            telegram_enabled=platforms.get("telegram", False), email_enabled=platforms.get("email", False)
        ),
        content=ContentConfig(),
    )
    return CaptionSpec.for_platforms(cfg)


class TestEmailPromptConsistency:
    def test_shipped_email_spec_has_no_examples_and_no_question_mandate(self) -> None:
        email = _real_specs(email=True)["email"]
        assert email.examples == ()
        assert "question" not in email.style.lower()
        assert "question" not in email.guidance.lower()

    def test_no_platform_ships_static_examples(self) -> None:
        from publisher_v2.config.static_loader import load_static_config

        for name, style in load_static_config().ai_prompts.platform_captions.items():
            assert not getattr(style, "examples", None), f"{name} ships static example captions"

    def test_mandated_closing_skips_closing_pattern_constraint(self) -> None:
        from publisher_v2.services.ai import build_platform_block

        spec = CaptionSpec(platform="email", style="short", hashtags="", max_length=240, closing="question")
        block = build_platform_block(1, "email", spec, platform_history=["Was it the knot? Tell me?"])
        # The line is singular since #138 ("Recent closing pattern to avoid"), so
        # the plural this used to look for could never appear either way.
        assert "closing pattern to avoid" not in block.lower()

    def test_any_closing_no_longer_emits_a_closing_pattern_constraint(self) -> None:
        """PUB-051 AC2 (was test_any_closing_keeps_closing_pattern_constraint, which asserted the line
        was present): with ``closing: any`` the "avoid: statement" line pushed a 30-word email toward
        the question #138 removed, so it is never rendered."""
        from publisher_v2.services.ai import build_platform_block

        spec = CaptionSpec(platform="email", style="short", hashtags="", max_length=240)
        assert spec.closing == "any"
        block = build_platform_block(1, "email", spec, platform_history=["Was it the knot?"])
        assert "closing pattern" not in block.lower()


class _Msg:
    def __init__(self, content: str) -> None:
        self.content = content


class _Resp:
    def __init__(self, content: str) -> None:
        self.choices = [type("C", (), {"message": _Msg(content)})()]
        self.usage = None


class _RecordingCompletions:
    """Fake OpenAI chat.completions: first draft copies history, the retry is fresh."""

    def __init__(self, first: dict[str, str], second: dict[str, str]) -> None:
        self.calls: list[dict[str, Any]] = []
        self._payloads = [first, second]

    async def create(self, **kwargs: Any) -> _Resp:
        self.calls.append(kwargs)
        payload = self._payloads[min(len(self.calls) - 1, 1)]
        return _Resp(json.dumps(payload))


def _angle_hits(prompt: str) -> Counter[str]:
    """PUB-051: which content-angle directives occur in a prompt, and how often."""
    from publisher_v2.utils.captions import CONTENT_ANGLES

    return Counter({key: prompt.count(text) for key, text in CONTENT_ANGLES.items() if prompt.count(text)})


async def test_regeneration_prompt_carries_exactly_one_angle_per_platform(monkeypatch) -> None:
    """PUB-051 AC1 (migrated from #138's ..._exactly_one_directive_per_platform).

    The old version counted STRUCTURE_DIRECTIVES, re-derived the rejected draft's
    structure with classify_caption_structure, and asserted the regeneration
    clause's wording; all three are gone with the structure rotation.
    """
    from publisher_v2.config.schema import OpenAIConfig
    from publisher_v2.core.models import ImageAnalysis
    from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI, VisionAnalyzerOpenAI

    history = {
        "telegram": ["Rope and light across her back tonight, slow and certain."],
        "email": ["Rope and light across her back tonight."],
    }
    completions = _RecordingCompletions(
        first={"telegram": history["telegram"][0], "email": history["email"][0]},
        second={"telegram": "Something else entirely.", "email": "Quiet, then the knot."},
    )
    fake_client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda **_kwargs: fake_client)
    cfg = OpenAIConfig(api_key="sk-test")
    service = AIService(VisionAnalyzerOpenAI(cfg), CaptionGeneratorOpenAI(cfg))
    specs = _real_specs(telegram=True, email=True)
    analysis = ImageAnalysis(description="d", mood="m", tags=["t"])

    _captions, _sd, _usages, angles = await service.create_multi_caption_pair_from_analysis(
        analysis, specs, history=history
    )

    assert len(completions.calls) == 2, "similarity gate should regenerate exactly once"
    retry_prompt = completions.calls[1]["messages"][-1]["content"]
    assert sum(_angle_hits(retry_prompt).values()) == len(specs), retry_prompt
    assert _angle_hits(retry_prompt) == Counter(angles.values())


class TestDirectivesFitThePlatform:
    """#138 review: a directive must never contradict the platform brief.

    PUB-051: test_word_limited_platform_never_gets_short_line and
    test_question_closing_never_gets_no_questions_directive pinned the deleted
    STRUCTURE_DIRECTIVES keys; the same contract against the new angle pool is
    test_caption_angle_rotation.py::test_pick_content_angle_respects_platform_exclusions.
    """

    def test_style_ignores_unknown_keys_and_strips_examples(self) -> None:
        assert PlatformCaptionStyle(style="s", some_future_key=1).style == "s"  # type: ignore[call-arg]
        # An older PV2_STATIC_CONFIG_DIR must not stop the app: stripped, not raised.
        assert PlatformCaptionStyle(style="s", examples=["x"]).style == "s"  # type: ignore[call-arg]


async def test_regeneration_gives_new_angle_only_to_offenders(monkeypatch) -> None:
    """Non-offending platforms keep their call-1 angle.

    PUB-051 AC1 changed one half of this #138 test: it asserted that a platform
    without history gets NO directive; now every platform gets exactly one angle
    in every call, history or not.
    """
    from publisher_v2.config.schema import OpenAIConfig
    from publisher_v2.core.models import ImageAnalysis
    from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI, VisionAnalyzerOpenAI

    history = {"telegram": ["Rope and light across her back tonight, slow and certain."]}
    completions = _RecordingCompletions(
        first={"telegram": history["telegram"][0], "email": "Something new."},
        second={"telegram": "Different now.", "email": "Something new."},
    )
    fake_client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda **_kwargs: fake_client)
    cfg = OpenAIConfig(api_key="sk-test")
    service = AIService(VisionAnalyzerOpenAI(cfg), CaptionGeneratorOpenAI(cfg))
    specs = _real_specs(telegram=True, email=True)
    _captions, _sd, _usages, angles = await service.create_multi_caption_pair_from_analysis(
        ImageAnalysis(description="d", mood="m", tags=["t"]), specs, history=history
    )
    first_prompt = completions.calls[0]["messages"][-1]["content"]
    retry_prompt = completions.calls[1]["messages"][-1]["content"]
    assert _angle_hits(retry_prompt) == Counter(angles.values()), "one angle per platform, email included"
    assert angles["email"] in _angle_hits(first_prompt), "the non-offender's angle changed on the retry"


async def test_single_platform_regeneration_prompt_carries_the_one_returned_angle(monkeypatch) -> None:
    """A lone offender's retry prompt carries exactly one angle, and it is the angle returned.

    Renamed from test_regeneration_angle_respects_platform_exclusions (PUB-051
    critique): its final assert checked the retry angle against
    ``excluded_directives``, which is empty for every platform now, so it could
    not fail. The exclusion contract itself is pinned by
    test_caption_angle_rotation.py::test_pick_content_angle_respects_platform_exclusions.
    """
    from publisher_v2.config.schema import OpenAIConfig
    from publisher_v2.core.models import ImageAnalysis
    from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI, VisionAnalyzerOpenAI

    draft = "The light fell across the rope and her shoulders tonight slowly."
    history = {
        "email": [
            "Warm skin. Then the knot.",
            "You hold still while the rope settles in.",
            "Light falls across the wall today. The rope waits in her lap quietly.",
            draft,
        ]
    }
    completions = _RecordingCompletions(first={"email": draft}, second={"email": "Something else."})
    fake_client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda **_kwargs: fake_client)
    cfg = OpenAIConfig(api_key="sk-test")
    service = AIService(VisionAnalyzerOpenAI(cfg), CaptionGeneratorOpenAI(cfg))
    specs = _real_specs(email=True)
    _captions, _sd, _usages, angles = await service.create_multi_caption_pair_from_analysis(
        ImageAnalysis(description="d", mood="m", tags=["t"]), specs, history=history
    )
    assert len(completions.calls) == 2
    retry_hits = _angle_hits(completions.calls[1]["messages"][-1]["content"])
    assert retry_hits == Counter({angles["email"]: 1}), retry_hits


class TestAStaleStaticConfigDirDoesNotStopTheApp:
    """#138: PV2_STATIC_CONFIG_DIR is a fleet-wide override (CONFIGURATION.md).

    A directory written before this change still carries `examples:`. Raising on
    it killed the CLI at generator construction and the web app inside its
    lifespan, so every request 500'd — for a key whose contents never reach a
    prompt. Malformed YAML in the same file only warns and falls back; this is a
    smaller problem than that.
    """

    @staticmethod
    def _write_stale_dir(tmp_path) -> str:
        import yaml

        ai = {
            "caption": {"system": "Persona.", "role_prompt": "Write:"},
            "platform_captions": {
                "email": {
                    "style": "warm",
                    "max_length": 240,
                    "hashtags": False,
                    "examples": ["A caption that shipped with the app once."],
                }
            },
        }
        (tmp_path / "ai_prompts.yaml").write_text(yaml.safe_dump(ai), encoding="utf-8")
        return str(tmp_path)

    def test_the_static_config_still_loads(self, tmp_path, monkeypatch) -> None:
        from publisher_v2.config.static_loader import load_static_config

        monkeypatch.setenv("PV2_STATIC_CONFIG_DIR", self._write_stale_dir(tmp_path))

        config = load_static_config()

        assert config.ai_prompts.platform_captions["email"].style == "warm"
        assert config.ai_prompts.platform_captions["email"].max_length == 240

    def test_the_caption_generator_still_builds(self, tmp_path, monkeypatch) -> None:
        from publisher_v2.config.schema import OpenAIConfig
        from publisher_v2.config.static_loader import get_static_config
        from publisher_v2.services.ai import CaptionGeneratorOpenAI

        monkeypatch.setenv("PV2_STATIC_CONFIG_DIR", self._write_stale_dir(tmp_path))
        get_static_config.cache_clear()
        try:
            generator = CaptionGeneratorOpenAI(OpenAIConfig(api_key="sk-test"))
            assert generator.system_prompt
        finally:
            get_static_config.cache_clear()

    def test_format_caption_still_works(self, tmp_path, monkeypatch) -> None:
        from publisher_v2.config.static_loader import get_static_config
        from publisher_v2.utils.captions import format_caption

        monkeypatch.setenv("PV2_STATIC_CONFIG_DIR", self._write_stale_dir(tmp_path))
        get_static_config.cache_clear()
        try:
            assert format_caption("email", "a caption") == "a caption"
        finally:
            get_static_config.cache_clear()


# PUB-051 AC2: TestTheClosingAvoidListLeavesAnOption (#138 capped the closing-avoid list
# to the most recent pattern) is removed — there is no closing-pattern line any more;
# see test_ai_prompt_payload.py::test_no_closing_pattern_line_is_ever_rendered.


def test_the_rejected_draft_counts_as_the_most_recent_caption() -> None:
    """#138, migrated to PUB-051's stored-angle rotation: the gate picks the offender's
    retry angle from ``[rejected_angle, *history_angles]`` — the draft first, because
    history is most-recent-first and ``pick_content_angle`` rotates on recency.

    Appending it instead makes it the *oldest* entry, and the angle just rejected
    becomes the least-recently-used one and is handed straight back. (The end-to-end
    version is test_caption_angle_rotation.py::test_regeneration_picks_a_different_angle_than_the_rejected_draft,
    which replaces test_the_gate_picks_the_retry_directive_with_the_draft_first.)
    """
    from publisher_v2.utils.captions import CONTENT_ANGLES, pick_content_angle

    pool = list(CONTENT_ANGLES)
    # Every key used once; the oldest is pool[0], so that is what the draft was written under.
    history = [*pool[1:], pool[0]]
    rejected = pick_content_angle(history)
    assert rejected == pool[0]

    as_most_recent = pick_content_angle([rejected, *history])
    as_oldest = pick_content_angle([*history, rejected])

    assert as_oldest == rejected
    assert as_most_recent != rejected


# ---------------------------------------------------------------------------
# PUB-051 AC7: a partial-publish retry reads the sidecar instead of re-paying AI
# ---------------------------------------------------------------------------


async def test_partial_retry_makes_zero_additional_ai_calls(monkeypatch, tmp_path) -> None:
    """AC7: telegram publishes, email fails; the retry publishes email with the caption
    the first run generated, read from the sidecar's ``caption_generated`` — and makes
    no OpenAI call at all. Real WorkflowOrchestrator, AIService, PublishStore and
    CaptionStore; only OpenAI, storage and the publishers are fakes.
    """
    from caption_pipeline_fakes import (
        FakeOpenAI,
        ScriptedPublisher,
        SidecarStorage,
        install_fake_openai,
        pipeline_config,
        real_ai_service,
    )
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from publisher_v2.core.workflow import WorkflowOrchestrator
    from publisher_v2.db.caption_store import CaptionStore
    from publisher_v2.db.models import Base, CaptionHistory
    from publisher_v2.db.publish_store import PublishStore

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        fake = FakeOpenAI(["telegram", "email"])
        install_fake_openai(monkeypatch, fake)
        telegram = ScriptedPublisher("telegram", [True])
        email = ScriptedPublisher("email", [False, True])
        orchestrator = WorkflowOrchestrator(
            pipeline_config(telegram=True, email=True),
            SidecarStorage(["a.jpg"]),
            real_ai_service(),
            [telegram, email],
            tenant="t1",
            caption_store=CaptionStore(factory),
            publish_store=PublishStore(factory),
        )

        first = await orchestrator.execute()
        assert first.partial is True
        calls_after_first = len(fake.calls)
        assert len(fake.caption_calls) == 1

        second = await orchestrator.execute()

        assert second.success is True
        assert len(fake.calls) == calls_after_first, "the retry paid for vision/caption again"
        assert len(fake.caption_calls) == 1, "caption completion ran more than once across both runs"
        assert fake.vision_calls and all(fake.calls.index(c) < calls_after_first for c in fake.vision_calls)
        # Email got the very caption run 1 generated for it (not a re-generation).
        assert len(email.captions) == 2
        assert email.captions[1] == email.captions[0]
        assert telegram.captions and len(telegram.captions) == 1

        async with factory() as session:
            rows = (await session.execute(select(CaptionHistory))).scalars().all()
        assert sorted(r.platform for r in rows) == ["email", "telegram"], "one row per platform that published"
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# PUB-051 critique follow-up: angles recorded when captions are reused or
# overridden, and _reuse_generated_captions' fall-back branches.
# ---------------------------------------------------------------------------


class _PartialPublishRig:
    """Real orchestrator/AIService/PublishStore/CaptionStore; fake OpenAI, storage and publishers.

    Run 1 publishes telegram and fails email, leaving a partial publish and a sidecar.
    """

    def __init__(self, monkeypatch, tmp_path) -> None:
        self.monkeypatch = monkeypatch
        self.tmp_path = tmp_path

    async def __aenter__(self) -> _PartialPublishRig:
        from caption_pipeline_fakes import (
            FakeOpenAI,
            ScriptedPublisher,
            SidecarStorage,
            install_fake_openai,
            pipeline_config,
            real_ai_service,
        )
        from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

        from publisher_v2.core.workflow import WorkflowOrchestrator
        from publisher_v2.db.caption_store import CaptionStore
        from publisher_v2.db.models import Base
        from publisher_v2.db.publish_store import PublishStore

        self.monkeypatch.setenv("XDG_CACHE_HOME", str(self.tmp_path))
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(bind=self.engine, expire_on_commit=False, class_=AsyncSession)
        self.fake = FakeOpenAI(["telegram", "email"])
        install_fake_openai(self.monkeypatch, self.fake)
        self.telegram = ScriptedPublisher("telegram", [True])
        self.email = ScriptedPublisher("email", [False, True])
        self.storage = SidecarStorage(["a.jpg"])
        self.orchestrator = WorkflowOrchestrator(
            pipeline_config(telegram=True, email=True),
            self.storage,
            real_ai_service(),
            [self.telegram, self.email],
            tenant="t1",
            caption_store=CaptionStore(self.factory),
            publish_store=PublishStore(self.factory),
        )
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.engine.dispose()

    def rewrite_sidecar_meta(self, **changes: Any) -> None:
        """Rewrite a.jpg's sidecar with metadata keys set (a value of None removes the key)."""
        from publisher_v2.services.sidecar_parser import parse_sidecar_text
        from publisher_v2.utils.captions import build_caption_sidecar

        sd, meta = parse_sidecar_text(self.storage.sidecars["a.jpg"])
        assert sd and meta is not None, "setup: run 1 wrote no sidecar"
        meta = dict(meta)
        for key, value in changes.items():
            if value is None:
                meta.pop(key, None)
            else:
                meta[key] = value
        self.storage.sidecars["a.jpg"] = build_caption_sidecar(sd, meta)

    async def rows(self) -> list[Any]:
        from sqlalchemy import select

        from publisher_v2.db.models import CaptionHistory

        async with self.factory() as session:
            return list((await session.execute(select(CaptionHistory).order_by(CaptionHistory.id))).scalars().all())


async def test_partial_retry_history_row_keeps_the_sidecar_angle(monkeypatch, tmp_path) -> None:
    """AC7 retry: the history row for a platform whose caption was reused from the sidecar stores
    the angle the sidecar's ``caption_angles`` recorded for it, not NULL.
    """
    from publisher_v2.utils.captions import CONTENT_ANGLES

    async with _PartialPublishRig(monkeypatch, tmp_path) as rig:
        first = await rig.orchestrator.execute()
        assert first.partial is True
        calls_after_first = len(rig.fake.calls)
        # Pin the recorded angles so the assertion does not depend on which angle run 1 happened to pick.
        recorded = {"telegram": "craft", "email": "atmosphere"}
        assert set(recorded.values()) <= set(CONTENT_ANGLES)
        rig.rewrite_sidecar_meta(caption_angles=recorded)

        second = await rig.orchestrator.execute()

        assert second.success is True
        assert len(rig.fake.calls) == calls_after_first, "setup: the retry did not reuse the sidecar captions"
        email_rows = [r for r in await rig.rows() if r.platform == "email"]
        assert len(email_rows) == 1, email_rows
        assert email_rows[0].angle == "atmosphere", f"retry row angle is {email_rows[0].angle!r}, not the sidecar's"


async def test_partial_retry_falls_back_to_ai_when_sidecar_download_fails(monkeypatch, tmp_path) -> None:
    """A retry whose sidecar read raises pays for a fresh AI stage and still publishes."""
    async with _PartialPublishRig(monkeypatch, tmp_path) as rig:
        first = await rig.orchestrator.execute()
        assert first.partial is True
        vision_before, captions_before = len(rig.fake.vision_calls), len(rig.fake.caption_calls)

        async def _boom(folder: str, filename: str) -> bytes | None:
            raise RuntimeError("sidecar download failed")

        monkeypatch.setattr(rig.storage, "download_sidecar_if_exists", _boom)

        second = await rig.orchestrator.execute()

        assert second.success is True
        assert len(rig.fake.vision_calls) == vision_before + 1, "no fresh vision call after the sidecar read failed"
        # At least one: the similarity gate may regenerate against the row run 1 stored.
        assert len(rig.fake.caption_calls) > captions_before, "no fresh caption call after the read failed"
        assert len(rig.email.captions) == 2


async def test_partial_retry_falls_back_to_ai_when_sidecar_lacks_a_platform(monkeypatch, tmp_path) -> None:
    """A sidecar whose ``caption_generated`` does not cover every platform still to publish means a fresh AI stage."""
    async with _PartialPublishRig(monkeypatch, tmp_path) as rig:
        first = await rig.orchestrator.execute()
        assert first.partial is True
        vision_before, captions_before = len(rig.fake.vision_calls), len(rig.fake.caption_calls)
        rig.rewrite_sidecar_meta(caption_generated={"telegram": "Only telegram was generated."})

        second = await rig.orchestrator.execute()

        assert second.success is True
        assert len(rig.fake.vision_calls) == vision_before + 1, "a partial sidecar was reused instead of a fresh run"
        assert len(rig.fake.caption_calls) > captions_before, "no fresh caption call for the missing platform"
        assert len(rig.email.captions) == 2


async def test_unedited_override_records_the_generated_angle_edited_one_does_not(monkeypatch, tmp_path) -> None:
    """Web publish via ``caption_overrides``: an override equal to the sidecar's ``caption_generated[platform]``
    (the operator did not edit it) records the sidecar's angle for that platform; an edited one records NULL.
    """
    from caption_pipeline_fakes import (
        FakeOpenAI,
        ScriptedPublisher,
        SidecarStorage,
        install_fake_openai,
        pipeline_config,
        real_ai_service,
    )
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from publisher_v2.core.workflow import WorkflowOrchestrator
    from publisher_v2.db.caption_store import CaptionStore
    from publisher_v2.db.models import Base, CaptionHistory
    from publisher_v2.utils.captions import build_caption_sidecar

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    generated = {
        "telegram": "Cold floorboards and warm hands, the harness finally sat right.",
        "instagram": "One frayed end, left alone on purpose.",
    }
    storage = SidecarStorage(["a.jpg"])
    storage.sidecars["a.jpg"] = build_caption_sidecar(
        "sd prompt, fine art",
        {"caption_generated": generated, "caption_angles": {"telegram": "craft", "instagram": "moment"}},
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        install_fake_openai(monkeypatch, FakeOpenAI(["telegram", "instagram"]))
        orchestrator = WorkflowOrchestrator(
            pipeline_config(telegram=True, instagram=True),
            storage,
            real_ai_service(),
            [ScriptedPublisher("telegram", [True]), ScriptedPublisher("instagram", [True])],
            tenant="t1",
            caption_store=CaptionStore(factory),
        )

        result = await orchestrator.execute(
            select_filename="a.jpg",
            caption_overrides={"telegram": generated["telegram"], "instagram": "The operator rewrote this one."},
        )

        assert result.success, result.error
        async with factory() as session:
            rows = (await session.execute(select(CaptionHistory))).scalars().all()
        angles = {r.platform: r.angle for r in rows}
        assert set(angles) == {"telegram", "instagram"}, angles
        assert angles["telegram"] == "craft", f"unedited override lost the generated angle: {angles}"
        assert angles["instagram"] is None, f"an edited override must not claim the generated angle: {angles}"
    finally:
        await engine.dispose()


async def test_override_angle_lookup_failure_stores_null_and_warns(monkeypatch, tmp_path, caplog) -> None:
    """``_override_angles`` fail-safe: a sidecar download that raises during the override
    history save means the rows store NULL angles, a ``caption_override_angles_failed``
    warning carrying no caption content is logged, and the publish still succeeds.
    """
    import logging

    from caption_pipeline_fakes import (
        FakeOpenAI,
        ScriptedPublisher,
        SidecarStorage,
        install_fake_openai,
        pipeline_config,
        real_ai_service,
    )
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from publisher_v2.core.workflow import WorkflowOrchestrator
    from publisher_v2.db.caption_store import CaptionStore
    from publisher_v2.db.models import Base, CaptionHistory
    from publisher_v2.utils.captions import build_caption_sidecar

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    generated = {
        "telegram": "Cold floorboards and warm hands, the harness finally sat right.",
        "instagram": "One frayed end, left alone on purpose.",
    }
    storage = SidecarStorage(["a.jpg"])
    # A sidecar that WOULD yield angles for both unedited overrides, were it readable.
    storage.sidecars["a.jpg"] = build_caption_sidecar(
        "sd prompt, fine art",
        {"caption_generated": generated, "caption_angles": {"telegram": "craft", "instagram": "moment"}},
    )
    sidecar_reads: list[str] = []

    async def _boom(folder: str, filename: str) -> bytes | None:
        sidecar_reads.append(filename)
        raise RuntimeError("sidecar download failed")

    monkeypatch.setattr(storage, "download_sidecar_if_exists", _boom)

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    caplog.set_level(logging.DEBUG)
    try:
        install_fake_openai(monkeypatch, FakeOpenAI(["telegram", "instagram"]))
        orchestrator = WorkflowOrchestrator(
            pipeline_config(telegram=True, instagram=True),
            storage,
            real_ai_service(),
            [ScriptedPublisher("telegram", [True]), ScriptedPublisher("instagram", [True])],
            tenant="t1",
            caption_store=CaptionStore(factory),
        )

        result = await orchestrator.execute(select_filename="a.jpg", caption_overrides=dict(generated))

        assert result.success, result.error
        assert sidecar_reads, "setup: the override path never tried to read the sidecar"
        async with factory() as session:
            rows = (await session.execute(select(CaptionHistory))).scalars().all()
        angles = {r.platform: r.angle for r in rows}
        assert set(angles) == {"telegram", "instagram"}, f"history rows missing after a failed angle lookup: {angles}"
        assert all(a is None for a in angles.values()), f"a failed lookup must store NULL angles: {angles}"

        warnings = [
            r
            for r in caplog.records
            if r.levelno == logging.WARNING and "caption_override_angles_failed" in r.getMessage()
        ]
        assert warnings, f"no caption_override_angles_failed warning logged: {caplog.text}"
        assert not any("caption_history_save_failed" in r.getMessage() for r in caplog.records), caplog.text
        for record in warnings:
            message = record.getMessage()
            for text in generated.values():
                assert text not in message, f"the warning leaked caption content: {message}"
            assert "sidecar download failed" not in message, f"the warning leaked the exception text: {message}"
    finally:
        await engine.dispose()


# ---------------------------------------------------------------------------
# PUB-051 last round: override edge cases (W2, W3).
# ---------------------------------------------------------------------------

_OVERRIDE_GENERATED = {
    "telegram": "Cold floorboards and warm hands, the harness finally sat right.",
    "instagram": "One frayed end, left alone on purpose.",
}
_OVERRIDE_ANGLES = {"telegram": "craft", "instagram": "moment"}


async def _run_override_publish(monkeypatch, tmp_path, overrides: dict[str, str], storage: Any = None):
    """One web-style ``caption_overrides`` publish of a.jpg through the real orchestrator and a real CaptionStore.

    a.jpg's sidecar starts out carrying ``_OVERRIDE_GENERATED`` and ``_OVERRIDE_ANGLES``.
    Returns ``(result, {platform: stored angle}, storage)``.
    """
    from caption_pipeline_fakes import (
        FakeOpenAI,
        ScriptedPublisher,
        SidecarStorage,
        install_fake_openai,
        pipeline_config,
        real_ai_service,
    )
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from publisher_v2.core.workflow import WorkflowOrchestrator
    from publisher_v2.db.caption_store import CaptionStore
    from publisher_v2.db.models import Base, CaptionHistory
    from publisher_v2.utils.captions import CONTENT_ANGLES, build_caption_sidecar

    assert set(_OVERRIDE_ANGLES.values()) <= set(CONTENT_ANGLES)
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    storage = storage or SidecarStorage(["a.jpg"])
    storage.sidecars["a.jpg"] = build_caption_sidecar(
        "sd prompt, fine art",
        {"caption_generated": dict(_OVERRIDE_GENERATED), "caption_angles": dict(_OVERRIDE_ANGLES)},
    )
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)
    try:
        install_fake_openai(monkeypatch, FakeOpenAI(["telegram", "instagram"]))
        orchestrator = WorkflowOrchestrator(
            pipeline_config(telegram=True, instagram=True),
            storage,
            real_ai_service(),
            [ScriptedPublisher("telegram", [True]), ScriptedPublisher("instagram", [True])],
            tenant="t1",
            caption_store=CaptionStore(factory),
        )
        result = await orchestrator.execute(select_filename="a.jpg", caption_overrides=overrides)
        async with factory() as session:
            rows = (await session.execute(select(CaptionHistory))).scalars().all()
        return result, {r.platform: r.angle for r in rows}, storage
    finally:
        await engine.dispose()


async def test_whitespace_padded_unedited_override_still_records_the_angle(monkeypatch, tmp_path) -> None:
    """W2: the web UI can hand back the generated caption with surrounding whitespace and newlines.

    That is still an unedited override, so the sidecar's angle is recorded for it.
    """
    padded = f"\n  \t{_OVERRIDE_GENERATED['telegram']}  \n\n"
    assert padded != _OVERRIDE_GENERATED["telegram"]

    result, angles, _storage = await _run_override_publish(
        monkeypatch, tmp_path, {"telegram": padded, "instagram": "The operator rewrote this one."}
    )

    assert result.success, result.error
    assert set(angles) == {"telegram", "instagram"}, angles
    assert angles["telegram"] == "craft", f"a whitespace-padded unedited override lost its angle: {angles}"
    assert angles["instagram"] is None, angles


async def test_override_publish_reads_the_sidecar_once(monkeypatch, tmp_path) -> None:
    """W3: an override publish downloads the sidecar once — the read ``update_sidecar_with_caption``
    already makes — and the unedited override's angle is still recorded from it.
    """
    from caption_pipeline_fakes import SidecarStorage

    storage = SidecarStorage(["a.jpg"])
    reads: list[str] = []
    real_download = storage.download_sidecar_if_exists

    async def _counting_download(folder: str, filename: str) -> bytes | None:
        reads.append(filename)
        return await real_download(folder, filename)

    monkeypatch.setattr(storage, "download_sidecar_if_exists", _counting_download)

    result, angles, storage = await _run_override_publish(
        monkeypatch,
        tmp_path,
        {"telegram": _OVERRIDE_GENERATED["telegram"], "instagram": "The operator rewrote this one."},
        storage=storage,
    )

    assert result.success, result.error
    from publisher_v2.services.sidecar_parser import parse_sidecar_text

    _sd, meta = parse_sidecar_text(storage.sidecars["a.jpg"])
    assert meta is not None and meta.get("caption_submitted"), "setup: update_sidecar_with_caption did not run"
    assert angles == {"telegram": "craft", "instagram": None}, angles
    assert reads == ["a.jpg"], f"the sidecar was downloaded {len(reads)} times during one override publish"
