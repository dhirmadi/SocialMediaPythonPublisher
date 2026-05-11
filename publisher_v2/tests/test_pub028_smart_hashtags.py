"""Tests for PUB-028: Smart Hashtag Generation.

Covers acceptance criteria AC-01..AC-13 from
``docs_v2/roadmap/PUB-028_smart-hashtag-generation.md``.
"""

from __future__ import annotations

import json

import pytest
from conftest import BaseDummyAnalyzer

from publisher_v2.config.schema import (
    ApplicationConfig,
    ContentConfig,
    DropboxConfig,
    EmailConfig,
    FeaturesConfig,
    OpenAIConfig,
    PlatformsConfig,
    StoragePathConfig,
)
from publisher_v2.config.static_loader import get_static_config
from publisher_v2.core.models import CaptionSpec, ImageAnalysis
from publisher_v2.services.ai import (
    AIService,
    CaptionGeneratorOpenAI,
    build_platform_block,
)
from publisher_v2.utils.captions import format_caption, normalize_generated_hashtags

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config(
    *,
    smart_hashtags_enabled: bool,
    hashtag_string: str = "#shibari #ropeart",
    telegram: bool = True,
    instagram: bool = False,
    email: bool = False,
) -> ApplicationConfig:
    return ApplicationConfig(
        dropbox=DropboxConfig(app_key="k", app_secret="s", refresh_token="r", image_folder="/Photos"),
        storage_paths=StoragePathConfig(image_folder="/Photos"),
        openai=OpenAIConfig(api_key="sk-test"),
        platforms=PlatformsConfig(
            telegram_enabled=telegram,
            instagram_enabled=instagram,
            email_enabled=email,
        ),
        telegram=None,
        instagram=None,
        email=EmailConfig(
            smtp_server="smtp.test",
            smtp_port=587,
            sender="f@t",
            recipient="t@t",
            password="p",
        )
        if email
        else None,
        content=ContentConfig(hashtag_string=hashtag_string, archive=False, debug=False),
        features=FeaturesConfig(smart_hashtags_enabled=smart_hashtags_enabled),
    )


def _make_analysis() -> ImageAnalysis:
    return ImageAnalysis(
        description="Fine-art portrait with soft light",
        mood="calm",
        tags=["portrait", "softlight"],
    )


def _default_openai_config() -> OpenAIConfig:
    return OpenAIConfig(
        api_key="sk-test",
        vision_model="gpt-4o",
        caption_model="gpt-4o-mini",
        sd_caption_enabled=True,
        sd_caption_single_call_enabled=True,
    )


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


# ---------------------------------------------------------------------------
# AC-01: CaptionSpec.smart_hashtags field + wiring through for_platforms()
# ---------------------------------------------------------------------------


class TestCaptionSpecSmartHashtagsField:
    def test_smart_hashtags_defaults_false(self) -> None:
        spec = CaptionSpec(platform="generic", style="x", hashtags="", max_length=100)
        assert spec.smart_hashtags is False

    def test_for_platforms_sets_smart_hashtags_true_when_flag_enabled(self) -> None:
        cfg = _make_config(smart_hashtags_enabled=True, telegram=True, instagram=True)
        specs = CaptionSpec.for_platforms(cfg)
        for spec in specs.values():
            assert spec.smart_hashtags is True

    def test_for_platforms_smart_hashtags_false_when_flag_disabled(self) -> None:
        cfg = _make_config(smart_hashtags_enabled=False, telegram=True, instagram=True)
        specs = CaptionSpec.for_platforms(cfg)
        for spec in specs.values():
            assert spec.smart_hashtags is False


# ---------------------------------------------------------------------------
# AC-02..AC-04: build_platform_block() branching
# ---------------------------------------------------------------------------


class TestBuildPlatformBlockHashtagBranches:
    def test_smart_with_seeds_emits_generate_and_seeds(self) -> None:
        """AC-02: smart=True + seeds → 'generate' + 'seed' instructions in prompt."""
        spec = CaptionSpec(
            platform="instagram",
            style="hook-first",
            hashtags="#shibari #ropeart",
            max_length=2200,
            smart_hashtags=True,
        )
        block = build_platform_block(1, "instagram", spec)
        low = block.lower()
        assert "generate" in low
        assert "seed" in low
        # Seed hashtags appear verbatim
        assert "#shibari" in block
        assert "#ropeart" in block

    def test_smart_no_seeds_emits_generate_without_seed_clause(self) -> None:
        """AC-03: smart=True + empty seeds → 'generate' without 'seed' instruction."""
        spec = CaptionSpec(
            platform="instagram",
            style="hook-first",
            hashtags="",
            max_length=2200,
            smart_hashtags=True,
        )
        block = build_platform_block(1, "instagram", spec)
        low = block.lower()
        assert "generate" in low
        assert "seed" not in low

    def test_verbatim_when_smart_disabled_with_seeds(self) -> None:
        """AC-04: smart=False + seeds → existing verbatim clause (pre-PUB-028)."""
        spec = CaptionSpec(
            platform="instagram",
            style="hook-first",
            hashtags="#shibari #ropeart",
            max_length=2200,
            smart_hashtags=False,
        )
        block = build_platform_block(1, "instagram", spec)
        # Pre-PUB-028: build_platform_block uses "Include hashtags: ..." verbatim append
        assert "Include hashtags: #shibari #ropeart." in block
        # And does NOT instruct the AI to generate hashtags
        assert "generate" not in block.lower()


# ---------------------------------------------------------------------------
# AC-05 + AC-08 + AC-12: generate() and generate_with_sd() branching
# ---------------------------------------------------------------------------


class TestGenerateHashtagBranching:
    @pytest.mark.asyncio
    async def test_generate_smart_with_seeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-05: generate() smart=True + seeds → prompt asks AI to generate, includes seeds."""
        completions = _FakeCompletions("a caption")
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _FakeClient(completions))
        gen = CaptionGeneratorOpenAI(_default_openai_config())
        spec = CaptionSpec(
            platform="generic",
            style="x",
            hashtags="#shibari #ropeart",
            max_length=2000,
            smart_hashtags=True,
        )
        await gen.generate(_make_analysis(), spec)
        prompt = completions.calls[0]["messages"][-1]["content"].lower()
        assert "generate" in prompt
        assert "seed" in prompt
        assert "#shibari" in prompt

    @pytest.mark.asyncio
    async def test_generate_smart_no_seeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-05: generate() smart=True + no seeds → 'generate' without seeds."""
        completions = _FakeCompletions("a caption")
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _FakeClient(completions))
        gen = CaptionGeneratorOpenAI(_default_openai_config())
        spec = CaptionSpec(
            platform="generic",
            style="x",
            hashtags="",
            max_length=2000,
            smart_hashtags=True,
        )
        await gen.generate(_make_analysis(), spec)
        prompt = completions.calls[0]["messages"][-1]["content"].lower()
        assert "generate" in prompt
        assert "seed" not in prompt

    @pytest.mark.asyncio
    async def test_generate_verbatim_when_smart_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-08/AC-12: generate() smart=False uses pre-PUB-028 verbatim clause."""
        completions = _FakeCompletions("a caption")
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _FakeClient(completions))
        gen = CaptionGeneratorOpenAI(_default_openai_config())
        spec = CaptionSpec(
            platform="generic",
            style="x",
            hashtags="#shibari #ropeart",
            max_length=2000,
            smart_hashtags=False,
        )
        await gen.generate(_make_analysis(), spec)
        prompt = completions.calls[0]["messages"][-1]["content"]
        # Pre-PUB-028 verbatim clause must appear unchanged
        assert "End with these hashtags verbatim: #shibari #ropeart." in prompt

    @pytest.mark.asyncio
    async def test_generate_with_sd_smart_with_seeds(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-05: generate_with_sd() applies same smart branching."""
        completions = _FakeCompletions(json.dumps({"caption": "c", "sd_caption": "s"}))
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _FakeClient(completions))
        gen = CaptionGeneratorOpenAI(_default_openai_config())
        spec = CaptionSpec(
            platform="generic",
            style="x",
            hashtags="#tag1",
            max_length=2000,
            smart_hashtags=True,
        )
        await gen.generate_with_sd(_make_analysis(), spec)
        prompt = completions.calls[0]["messages"][-1]["content"].lower()
        assert "generate" in prompt
        assert "seed" in prompt
        assert "#tag1" in prompt

    @pytest.mark.asyncio
    async def test_generate_with_sd_verbatim_when_smart_disabled(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-08/AC-12: generate_with_sd() smart=False uses pre-PUB-028 verbatim clause."""
        completions = _FakeCompletions(json.dumps({"caption": "c", "sd_caption": "s"}))
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _FakeClient(completions))
        gen = CaptionGeneratorOpenAI(_default_openai_config())
        spec = CaptionSpec(
            platform="generic",
            style="x",
            hashtags="#tag1",
            max_length=2000,
            smart_hashtags=False,
        )
        await gen.generate_with_sd(_make_analysis(), spec)
        prompt = completions.calls[0]["messages"][-1]["content"]
        assert "End with these hashtags verbatim: #tag1." in prompt


# ---------------------------------------------------------------------------
# AC-06 + AC-07: ai_prompts.yaml platform hashtag flags
# ---------------------------------------------------------------------------


class TestAiPromptsYamlPlatformHashtags:
    def test_telegram_hashtags_disabled(self) -> None:
        """AC-06: telegram.hashtags == false."""
        registry = get_static_config().ai_prompts.platform_captions
        assert registry["telegram"].hashtags is False

    def test_email_hashtags_disabled_regression(self) -> None:
        """AC-07: email.hashtags remains false."""
        registry = get_static_config().ai_prompts.platform_captions
        assert registry["email"].hashtags is False

    def test_telegram_caption_spec_has_no_hashtag_seeds(self) -> None:
        """AC-06: With telegram.hashtags=false, telegram CaptionSpec.hashtags is empty."""
        cfg = _make_config(smart_hashtags_enabled=False, telegram=True)
        specs = CaptionSpec.for_platforms(cfg)
        assert specs["telegram"].hashtags == ""


# ---------------------------------------------------------------------------
# AC-09: normalize_generated_hashtags()
# ---------------------------------------------------------------------------


class TestNormalizeGeneratedHashtags:
    def test_lowercases_hashtags(self) -> None:
        text = "Caption #FineArt #Portrait"
        out = normalize_generated_hashtags(text)
        assert "#fineart" in out
        assert "#portrait" in out
        assert "#FineArt" not in out

    def test_deduplicates_preserving_order(self) -> None:
        text = "Caption #portrait #softlight #portrait #PORTRAIT"
        out = normalize_generated_hashtags(text)
        # Only one #portrait
        assert out.count("#portrait") == 1
        # softlight is preserved in order
        assert "#softlight" in out

    def test_caps_at_max_count(self) -> None:
        many = " ".join(f"#tag{i}" for i in range(50))
        out = normalize_generated_hashtags(many, max_count=10)
        # Count actual hashtags
        import re

        tags = re.findall(r"#\w+", out)
        assert len(tags) == 10

    def test_text_without_hashtags_unchanged(self) -> None:
        text = "A plain caption without any tags."
        out = normalize_generated_hashtags(text)
        assert out == text

    def test_hashtags_have_hash_prefix(self) -> None:
        text = "Caption #PORTRAIT #softlight"
        out = normalize_generated_hashtags(text)
        import re

        tags = re.findall(r"#\w+", out)
        assert all(t.startswith("#") for t in tags)


# ---------------------------------------------------------------------------
# AC-10: No extra OpenAI calls in smart hashtag mode
# ---------------------------------------------------------------------------


class TestNoExtraOpenAICalls:
    @pytest.mark.asyncio
    async def test_smart_path_uses_single_openai_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-10: enabling smart_hashtags must not add an OpenAI call."""
        completions = _FakeCompletions("caption with #generated #tags")
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _FakeClient(completions))
        gen = CaptionGeneratorOpenAI(_default_openai_config())
        spec = CaptionSpec(
            platform="generic",
            style="x",
            hashtags="#seed",
            max_length=2000,
            smart_hashtags=True,
        )
        await gen.generate(_make_analysis(), spec)
        assert len(completions.calls) == 1

    @pytest.mark.asyncio
    async def test_smart_multi_path_uses_single_openai_call(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-10: multi-platform smart path also uses a single call."""
        response = json.dumps({"telegram": "t", "instagram": "i", "email": "e"})
        completions = _FakeCompletions(response)
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _FakeClient(completions))
        gen = CaptionGeneratorOpenAI(_default_openai_config())
        specs = {
            "telegram": CaptionSpec(
                platform="telegram", style="conv", hashtags="", max_length=4096, smart_hashtags=True
            ),
            "instagram": CaptionSpec(
                platform="instagram", style="hook", hashtags="#seed", max_length=2200, smart_hashtags=True
            ),
            "email": CaptionSpec(platform="email", style="q", hashtags="", max_length=240, smart_hashtags=True),
        }
        await gen.generate_multi(_make_analysis(), specs)
        assert len(completions.calls) == 1


# ---------------------------------------------------------------------------
# AC-11: Preview displays hashtag count
# ---------------------------------------------------------------------------


class TestPreviewHashtagCount:
    def test_print_caption_displays_hashtag_count(self, capsys: pytest.CaptureFixture[str]) -> None:
        """AC-11: print_caption shows 'Hashtags: N' line."""
        from publisher_v2.utils.preview import print_caption

        spec = CaptionSpec(platform="instagram", style="hook", hashtags="", max_length=2200)
        caption = "A photo with #tag1 #tag2 #tag3"
        print_caption(caption, spec, model="gpt-4o-mini", hashtag_count=caption.count("#"))
        out = capsys.readouterr().out
        assert "Hashtags:" in out
        assert "3" in out


# ---------------------------------------------------------------------------
# AC-12: Byte-identical pre-PUB-028 prompt when smart=False
# ---------------------------------------------------------------------------


class TestByteIdenticalPrePub028:
    def test_build_platform_block_byte_identical_when_smart_false(self) -> None:
        """AC-12: With smart=False, build_platform_block output is byte-identical to pre-PUB-028."""
        spec = CaptionSpec(
            platform="instagram",
            style="hook-first, hashtags naturally",
            hashtags="#shibari #ropeart",
            max_length=2200,
            smart_hashtags=False,
        )
        block = build_platform_block(2, "instagram", spec)
        expected = (
            "2. instagram: hook-first, hashtags naturally, up to 2200 chars. Include hashtags: #shibari #ropeart."
        )
        assert block == expected

    @pytest.mark.asyncio
    async def test_generate_prompt_byte_identical_when_smart_false(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-12: generate() prompt is byte-identical to pre-PUB-028 when smart=False."""
        completions_smart_off = _FakeCompletions("c")
        monkeypatch.setattr("publisher_v2.services.ai.AsyncOpenAI", lambda api_key: _FakeClient(completions_smart_off))
        gen = CaptionGeneratorOpenAI(_default_openai_config())
        # Use a CaptionSpec that intentionally omits smart_hashtags (default False)
        spec = CaptionSpec(
            platform="generic",
            style="x",
            hashtags="#shibari #ropeart",
            max_length=2000,
        )
        await gen.generate(_make_analysis(), spec)
        prompt = completions_smart_off.calls[0]["messages"][-1]["content"]
        # The pre-PUB-028 verbatim hashtag clause must appear unchanged
        assert " End with these hashtags verbatim: #shibari #ropeart." in prompt
        # And there must be no smart-hashtag instructions
        assert "Generate" not in prompt or "Generate relevant hashtags" not in prompt
        assert "seed" not in prompt.lower()


# ---------------------------------------------------------------------------
# AC-13: Existing tests still pass — covered implicitly by the rest of the suite.
# ---------------------------------------------------------------------------


class TestAIServiceSmokeStillWorks:
    @pytest.mark.asyncio
    async def test_ai_service_create_caption_pair_still_works(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """AC-13: AIService.create_caption_pair still works end-to-end with new field."""
        cfg = _default_openai_config()
        gen = CaptionGeneratorOpenAI(cfg)

        async def fake_generate_with_sd(analysis: ImageAnalysis, spec: CaptionSpec):
            return {"caption": "c", "sd_caption": "s"}, None

        monkeypatch.setattr(gen, "generate_with_sd", fake_generate_with_sd)

        ai = AIService(analyzer=BaseDummyAnalyzer(), generator=gen)  # type: ignore[arg-type]
        spec = CaptionSpec(
            platform="generic",
            style="minimal",
            hashtags="#tag",
            max_length=100,
            smart_hashtags=True,
        )
        caption, sd = await ai.create_caption_pair("http://tmp", spec)
        assert caption == "c"
        assert sd == "s"


# ---------------------------------------------------------------------------
# AC-09 (integration): normalize_generated_hashtags wired into format_caption
# ---------------------------------------------------------------------------


class TestFormatCaptionSmartHashtagsIntegration:
    def test_format_caption_smart_lowercases_and_dedupes(self) -> None:
        """When smart_hashtags=True, format_caption applies normalize_generated_hashtags."""
        text = "A pretty photo #FineArt #PORTRAIT #fineart"
        out = format_caption("telegram", text, smart_hashtags=True)
        # Lowercased + deduped
        assert "#fineart" in out
        assert "#portrait" in out
        assert "#FineArt" not in out
        assert "#PORTRAIT" not in out
        # Only one #fineart
        assert out.count("#fineart") == 1

    def test_format_caption_default_disabled_preserves_pre_pub028(self) -> None:
        """Without smart_hashtags=True, format_caption behavior is byte-identical to pre-PUB-028."""
        text = "A pretty photo #FineArt #PORTRAIT"
        out = format_caption("telegram", text)
        # Mixed case preserved (pre-PUB-028 behavior)
        assert "#FineArt" in out
        assert "#PORTRAIT" in out

    def test_format_caption_smart_email_still_strips_hashtags(self) -> None:
        """Email path strips all hashtags regardless of smart_hashtags flag."""
        text = "Engagement question? #FineArt #portrait"
        out = format_caption("email", text, smart_hashtags=True)
        assert "#" not in out
