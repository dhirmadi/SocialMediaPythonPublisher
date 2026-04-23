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
    """AC1: PlatformCaptionStyle supports an optional examples list."""

    def test_examples_default_empty(self) -> None:
        style = PlatformCaptionStyle()
        assert style.examples == []

    def test_examples_accepts_list(self) -> None:
        style = PlatformCaptionStyle(examples=["Example one", "Example two"])
        assert style.examples == ["Example one", "Example two"]

    def test_examples_preserved_in_yaml_roundtrip(self) -> None:
        style = PlatformCaptionStyle(style="conversational", examples=["Test"], max_length=4096, hashtags=True)
        data = style.model_dump()
        rebuilt = PlatformCaptionStyle(**data)
        assert rebuilt.examples == ["Test"]


class TestExamplesInPrompt:
    """AC2: When examples is non-empty, the prompt includes a Voice examples block."""

    def test_prompt_includes_examples_block(self) -> None:
        from publisher_v2.services.ai import build_platform_block

        spec = CaptionSpec(
            platform="telegram",
            style="conversational",
            hashtags="#art",
            max_length=4096,
            examples=("The way light catches jute", "New work. Three hours of tying"),
            guidance="",
        )
        block = build_platform_block(1, "telegram", spec)
        assert "Voice examples" in block
        assert "The way light catches jute" in block
        assert "New work. Three hours of tying" in block

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
        assert cfg.window_size == 8
        assert cfg.max_tokens_budget == 1000

    def test_caption_history_custom(self) -> None:
        from publisher_v2.config.static_loader import CaptionHistoryConfig

        cfg = CaptionHistoryConfig(window_size=5, max_tokens_budget=500)
        assert cfg.window_size == 5
        assert cfg.max_tokens_budget == 500


class TestCaptionHistoryPrompt:
    """AC6/AC8: History is injected into prompt with anti-repetition instructions."""

    def test_build_history_block_with_captions(self) -> None:
        from publisher_v2.services.ai import build_history_block

        captions = ["Caption one", "Caption two", "Caption three"]
        block = build_history_block(captions)
        assert "recent captions" in block.lower()
        assert "1. " in block
        assert "Caption one" in block
        assert "Caption three" in block
        assert "DO NOT repeat" in block
        assert "DIFFERENT" in block

    def test_build_history_block_empty(self) -> None:
        from publisher_v2.services.ai import build_history_block

        assert build_history_block([]) == ""


class TestHistoryGracefulFailure:
    """AC7: If sidecar retrieval fails, generation proceeds without history."""

    async def test_fetch_history_returns_empty_on_error(self) -> None:
        from publisher_v2.services.ai import fetch_caption_history

        class _FailingStorage:
            async def list_images(self, folder: str) -> list[str]:
                raise OSError("Storage unavailable")

            async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None:
                return None

        result = await fetch_caption_history(_FailingStorage(), "images/", window_size=8, max_tokens_budget=1000)
        assert result == []

    async def test_fetch_history_returns_empty_on_no_sidecars(self) -> None:
        from publisher_v2.services.ai import fetch_caption_history

        class _EmptyStorage:
            async def list_images(self, folder: str) -> list[str]:
                return ["img1.jpg", "img2.jpg"]

            async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None:
                return None

        result = await fetch_caption_history(_EmptyStorage(), "images/", window_size=8, max_tokens_budget=1000)
        assert result == []

    async def test_window_size_zero_returns_empty(self) -> None:
        """window_size=0 returns empty list (edge case: images[-0:] would return all)."""
        from publisher_v2.services.ai import fetch_caption_history

        class _Storage:
            async def list_images(self, folder: str) -> list[str]:
                return ["img1.jpg"]

            async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None:
                return b'{"caption": "test"}'

        result = await fetch_caption_history(_Storage(), "images/", window_size=0, max_tokens_budget=1000)
        assert result == []


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


class TestHistoryUsesPublishedCaption:
    """AC10: History uses caption (published) not caption_generated."""

    async def test_fetch_prefers_caption_over_caption_generated(self) -> None:
        from publisher_v2.services.ai import fetch_caption_history

        sidecar_content = json.dumps(
            {"caption": "The edited published version", "caption_generated": "The AI original version"}
        ).encode()

        class _SidecarStorage:
            async def list_images(self, folder: str) -> list[str]:
                return ["img1.jpg"]

            async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None:
                return sidecar_content

        result = await fetch_caption_history(_SidecarStorage(), "images/", window_size=8, max_tokens_budget=1000)
        assert len(result) == 1
        assert result[0] == "The edited published version"

    async def test_fetch_fallback_to_caption_generated(self) -> None:
        """When sidecar has only caption_generated (no caption), use caption_generated."""
        from publisher_v2.services.ai import fetch_caption_history

        sidecar_content = json.dumps({"caption_generated": "The AI original version"}).encode()

        class _Storage:
            async def list_images(self, folder: str) -> list[str]:
                return ["img1.jpg"]

            async def download_sidecar_if_exists(self, folder: str, filename: str) -> bytes | None:
                return sidecar_content

        result = await fetch_caption_history(_Storage(), "images/", window_size=8, max_tokens_budget=1000)
        assert len(result) == 1
        assert result[0] == "The AI original version"


class TestSidecarFormatParsing:
    """C3: Correct handling of real text-format sidecars and edge cases."""

    def test_extract_from_text_sidecar_with_caption_metadata(self) -> None:
        """Real text sidecar with caption metadata line."""
        from publisher_v2.services.ai import _extract_caption_from_sidecar

        sidecar = b"SD prompt for stable diffusion\n\n# ---\n# image_file: test.jpg\n# caption: The published caption\n"
        assert _extract_caption_from_sidecar(sidecar) == "The published caption"

    def test_extract_from_text_sidecar_without_caption_returns_empty(self) -> None:
        """Real text sidecar without caption metadata returns empty (NOT the SD prompt)."""
        from publisher_v2.services.ai import _extract_caption_from_sidecar

        sidecar = b"SD prompt for stable diffusion\n\n# ---\n# image_file: test.jpg\n# sha256: abc\n"
        assert _extract_caption_from_sidecar(sidecar) == ""

    def test_extract_from_json_sidecar(self) -> None:
        """JSON sidecar format is handled correctly."""
        from publisher_v2.services.ai import _extract_caption_from_sidecar

        sidecar = json.dumps({"caption": "JSON caption"}).encode()
        assert _extract_caption_from_sidecar(sidecar) == "JSON caption"

    def test_extract_from_malformed_json(self) -> None:
        """Malformed JSON falls back to metadata line parsing."""
        from publisher_v2.services.ai import _extract_caption_from_sidecar

        sidecar = b"{broken json\n\n# ---\n# caption: Fallback caption\n"
        assert _extract_caption_from_sidecar(sidecar) == "Fallback caption"

    def test_extract_skips_oversized_sidecar(self) -> None:
        """Sidecars larger than 64KB are skipped (H1 size guard)."""
        from publisher_v2.services.ai import _extract_caption_from_sidecar

        huge = b'{"caption": "test"}' + b" " * (65 * 1024)
        assert _extract_caption_from_sidecar(huge) == ""

    def test_extract_empty_data(self) -> None:
        from publisher_v2.services.ai import _extract_caption_from_sidecar

        assert _extract_caption_from_sidecar(b"") == ""
        assert _extract_caption_from_sidecar(b"   ") == ""

    def test_extract_caption_generated_from_metadata(self) -> None:
        """Text sidecar with caption_generated metadata (no caption key)."""
        from publisher_v2.services.ai import _extract_caption_from_sidecar

        sidecar = b"SD prompt\n\n# ---\n# caption_generated: Original AI caption\n"
        assert _extract_caption_from_sidecar(sidecar) == "Original AI caption"


# ---------------------------------------------------------------------------
# Part D: Operator edit tracking
# ---------------------------------------------------------------------------


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
        history = ["Previous caption one", "Previous caption two"]

        await gen.generate_multi(analysis, specs, history=history)

        assert len(captured_prompts) == 1
        prompt = captured_prompts[0]
        assert "Previous caption one" in prompt
        assert "Previous caption two" in prompt
        assert "DO NOT repeat" in prompt


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
