"""Tests for PUB-035: Caption Context Intelligence.

Covers all four parts:
  A — Style examples in platform registry
  B — Trend guidance per platform
  C — Caption history as sliding context window
  D — Operator edit tracking in sidecars
"""

from __future__ import annotations

import json
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
        assert "closing pattern to avoid" in block.lower()
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
        assert "closing pattern to avoid" in block.lower()
        for full in history:
            assert full not in block
        # First six words of each opening are present as the avoid-list.
        assert "Soft rope steady hands and a" in block
        assert "Did you see how the light" in block

    def test_platform_block_includes_structure_directive(self) -> None:
        from publisher_v2.core.models import CaptionSpec
        from publisher_v2.services.ai import build_platform_block

        spec = CaptionSpec(platform="email", style="s", hashtags="", max_length=240)
        block = build_platform_block(1, "email", spec, platform_history=["An earlier caption line here."])
        assert "Structure directive:" in block


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
        assert "closing patterns" not in block.lower()

    def test_any_closing_keeps_closing_pattern_constraint(self) -> None:
        from publisher_v2.services.ai import build_platform_block

        spec = CaptionSpec(platform="email", style="short", hashtags="", max_length=240)
        assert spec.closing == "any"
        block = build_platform_block(1, "email", spec, platform_history=["Was it the knot?"])
        assert "closing pattern to avoid" in block.lower()


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


async def test_regeneration_prompt_carries_exactly_one_directive_per_platform(monkeypatch) -> None:
    from publisher_v2.config.schema import OpenAIConfig
    from publisher_v2.core.models import ImageAnalysis
    from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI, VisionAnalyzerOpenAI

    history = {
        "telegram": ["Rope and light across her back tonight, slow and certain."],
        "email": ["Rope and light across her back tonight."],
    }
    completions = _RecordingCompletions(
        first={"telegram": history["telegram"][0], "email": history["email"][0], "sd_caption": "x"},
        second={"telegram": "Something else entirely.", "email": "Quiet, then the knot.", "sd_caption": "x"},
    )
    fake_client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda **_kwargs: fake_client)
    cfg = OpenAIConfig(api_key="sk-test")
    service = AIService(VisionAnalyzerOpenAI(cfg), CaptionGeneratorOpenAI(cfg))
    specs = _real_specs(telegram=True, email=True)
    analysis = ImageAnalysis(description="d", mood="m", tags=["t"])

    await service.create_multi_caption_pair_from_analysis(analysis, specs, history=history)

    assert len(completions.calls) == 2, "similarity gate should regenerate exactly once"
    retry_prompt = completions.calls[1]["messages"][-1]["content"]
    from publisher_v2.utils.captions import STRUCTURE_DIRECTIVES

    directive_hits = sum(retry_prompt.count(d) for d in STRUCTURE_DIRECTIVES.values())
    assert directive_hits == len(specs), retry_prompt
    assert retry_prompt.count("Structure directive:") == len(specs)


class TestDirectivesFitThePlatform:
    """#138 review: a structure directive must never contradict the platform brief."""

    def test_word_limited_platform_never_gets_short_line(self) -> None:
        from publisher_v2.services.ai import build_platform_block
        from publisher_v2.utils.captions import STRUCTURE_DIRECTIVES

        spec = CaptionSpec(platform="email", style="s", hashtags="", max_length=240)
        # Every other structure used recently -> plain LRU would pick short_line.
        from publisher_v2.utils.captions import pick_structure_directive

        history = [
            "The light fell across the rope and her shoulders tonight slowly.",  # declarative
            "Warm skin. Then the knot.",  # fragment
            "You hold still while the rope settles in.",  # second_person
            "Light falls across the wall today. The rope waits in her lap quietly.",  # observation
        ]
        assert pick_structure_directive(history) == STRUCTURE_DIRECTIVES["short_line"]
        block = build_platform_block(1, "email", spec, platform_history=history)
        assert STRUCTURE_DIRECTIVES["short_line"] not in block

    def test_question_closing_never_gets_no_questions_directive(self) -> None:
        from publisher_v2.services.ai import build_platform_block
        from publisher_v2.utils.captions import STRUCTURE_DIRECTIVES

        spec = CaptionSpec(platform="telegram", style="s", hashtags="", max_length=4096, closing="question")
        from publisher_v2.utils.captions import pick_structure_directive

        # Every other structure used recently -> plain LRU would pick observation.
        history = [
            "The light fell across the rope and her shoulders tonight slowly.",  # declarative
            "Warm skin. Then the knot.",  # fragment
            "You hold still while the rope settles in.",  # second_person
            "Rope settles on warm skin tonight",  # short_line
        ]
        assert pick_structure_directive(history) == STRUCTURE_DIRECTIVES["observation"]
        block = build_platform_block(1, "telegram", spec, platform_history=history)
        assert STRUCTURE_DIRECTIVES["observation"] not in block

    def test_style_ignores_unknown_keys_and_strips_examples(self) -> None:
        assert PlatformCaptionStyle(style="s", some_future_key=1).style == "s"  # type: ignore[call-arg]
        # An older PV2_STATIC_CONFIG_DIR must not stop the app: stripped, not raised.
        assert PlatformCaptionStyle(style="s", examples=["x"]).style == "s"  # type: ignore[call-arg]


async def test_regeneration_gives_new_directive_only_to_offenders(monkeypatch) -> None:
    """Non-offending platforms keep their call-1 directive; a platform without history gets none."""
    from publisher_v2.config.schema import OpenAIConfig
    from publisher_v2.core.models import ImageAnalysis
    from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI, VisionAnalyzerOpenAI

    history = {"telegram": ["Rope and light across her back tonight, slow and certain."]}
    completions = _RecordingCompletions(
        first={"telegram": history["telegram"][0], "email": "Something new.", "sd_caption": "x"},
        second={"telegram": "Different now.", "email": "Something new.", "sd_caption": "x"},
    )
    fake_client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda **_kwargs: fake_client)
    cfg = OpenAIConfig(api_key="sk-test")
    service = AIService(VisionAnalyzerOpenAI(cfg), CaptionGeneratorOpenAI(cfg))
    specs = _real_specs(telegram=True, email=True)
    await service.create_multi_caption_pair_from_analysis(
        ImageAnalysis(description="d", mood="m", tags=["t"]), specs, history=history
    )
    retry_prompt = completions.calls[1]["messages"][-1]["content"]
    email_block = retry_prompt.split("2. email:")[1].split("Image analysis:")[0]
    assert "Structure directive" not in email_block


async def test_regeneration_directive_respects_platform_exclusions(monkeypatch) -> None:
    """An email offender whose history + draft would LRU-pick short_line gets another directive on retry."""
    from publisher_v2.config.schema import OpenAIConfig
    from publisher_v2.core.models import ImageAnalysis
    from publisher_v2.services.ai import AIService, CaptionGeneratorOpenAI, VisionAnalyzerOpenAI
    from publisher_v2.utils.captions import STRUCTURE_DIRECTIVES, pick_structure_directive

    draft = "The light fell across the rope and her shoulders tonight slowly."  # declarative
    history = {
        "email": [
            "Warm skin. Then the knot.",  # fragment
            "You hold still while the rope settles in.",  # second_person
            "Light falls across the wall today. The rope waits in her lap quietly.",  # observation
            draft,
        ]
    }
    assert pick_structure_directive([draft, *history["email"]]) == STRUCTURE_DIRECTIVES["short_line"]
    completions = _RecordingCompletions(
        first={"email": draft, "sd_caption": "x"}, second={"email": "Something else.", "sd_caption": "x"}
    )
    fake_client = type("Client", (), {"chat": type("Chat", (), {"completions": completions})()})()
    monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda **_kwargs: fake_client)
    cfg = OpenAIConfig(api_key="sk-test")
    service = AIService(VisionAnalyzerOpenAI(cfg), CaptionGeneratorOpenAI(cfg))
    await service.create_multi_caption_pair_from_analysis(
        ImageAnalysis(description="d", mood="m", tags=["t"]), _real_specs(email=True), history=history
    )
    assert len(completions.calls) == 2
    retry_prompt = completions.calls[1]["messages"][-1]["content"]
    assert STRUCTURE_DIRECTIVES["short_line"] not in retry_prompt
    assert retry_prompt.count("Structure directive:") == 1


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


class TestTheClosingAvoidListLeavesAnOption:
    """#138: there are three closing patterns in all (question, statement, fragment).

    Listing every closing seen in the history left the model one option with two
    entries and none with three — an instruction it cannot satisfy, sitting next
    to a structure directive telling it to open with a statement.
    """

    @staticmethod
    def _spec() -> CaptionSpec:
        return CaptionSpec(platform="email", style="short", hashtags="", max_length=240)

    def test_only_the_most_recent_closing_is_named(self) -> None:
        from publisher_v2.services.ai import build_platform_block

        history = ["A statement ending.", "Was it the knot?", "a trailing fragment"]

        block = build_platform_block(1, "email", self._spec(), platform_history=history)

        line = next(line for line in block.splitlines() if "closing pattern to avoid" in line.lower())
        named = [p for p in ("question", "statement", "fragment") if p in line.lower()]
        assert named == ["fragment"], line

    def test_the_flat_history_block_caps_it_too(self) -> None:
        from publisher_v2.services.ai import build_history_block

        block = build_history_block(["A statement ending.", "Was it the knot?", "a trailing fragment"])

        line = next(line for line in block.splitlines() if "closing pattern to avoid" in line.lower())
        named = [p for p in ("question", "statement", "fragment") if p in line.lower()]
        assert named == ["fragment"], line
