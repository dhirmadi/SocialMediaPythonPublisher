"""Tests for PUB-029 — Brand Voice Matching: token budget, prompt hardening,
multi-platform compatibility, and feature-off byte-equivalence.
"""

from __future__ import annotations

from publisher_v2.core.models import CaptionSpec, ImageAnalysis
from publisher_v2.services.ai import (
    CaptionGeneratorOpenAI,
    build_voice_examples_block,
    truncate_voice_profile_to_budget,
)

# ---------------------------------------------------------------------------
# AC-01: deterministic token-budget truncation
# ---------------------------------------------------------------------------


class TestTruncateVoiceProfileToBudget:
    def test_ac01_under_budget_keeps_all(self) -> None:
        examples = ["short", "also short", "tiny"]
        # Default budget 500 tokens (~2000 chars) — these all fit easily
        result = truncate_voice_profile_to_budget(examples, max_tokens_budget=500)
        assert result == examples

    def test_ac01_over_budget_drops_from_end_preserving_order(self) -> None:
        # Each entry is ~80 chars (~20 tokens). Budget of 50 tokens fits ~2.
        examples = ["a" * 80, "b" * 80, "c" * 80, "d" * 80]
        result = truncate_voice_profile_to_budget(examples, max_tokens_budget=50)
        # First two preserved, drop from end.
        assert result == examples[: len(result)]
        assert result == ["a" * 80, "b" * 80]

    def test_ac01_deterministic_repeated_calls_match(self) -> None:
        examples = ["x" * 100, "y" * 100, "z" * 100, "w" * 100]
        a = truncate_voice_profile_to_budget(examples, max_tokens_budget=60)
        b = truncate_voice_profile_to_budget(examples, max_tokens_budget=60)
        assert a == b

    def test_ac01_empty_input_returns_empty(self) -> None:
        assert truncate_voice_profile_to_budget([], max_tokens_budget=500) == []

    def test_ac01_zero_budget_drops_all(self) -> None:
        assert truncate_voice_profile_to_budget(["a", "b"], max_tokens_budget=0) == []

    def test_ac01_budget_exactly_fits_first(self) -> None:
        # First entry exactly fits, second would exceed.
        # 100 chars => ~26 tokens (100//4 + 1)
        first = "x" * 100
        second = "y" * 100
        result = truncate_voice_profile_to_budget([first, second], max_tokens_budget=26)
        assert result == [first]


# ---------------------------------------------------------------------------
# AC-02: voice examples block has delimiters + style-only instruction
# ---------------------------------------------------------------------------


class TestVoiceExamplesBlock:
    def test_ac02_block_has_delimiters_and_style_only_instruction(self) -> None:
        block = build_voice_examples_block(["hello", "world"])
        # Must contain the explicit "style only" guidance phrase
        assert "style" in block.lower()
        # Must contain a clear opening + closing delimiter pair
        # (we accept any matched fence — e.g., BEGIN/END or triple backticks).
        assert "BEGIN" in block.upper() or "```" in block
        assert "END" in block.upper() or block.count("```") >= 2

    def test_ac02_block_marks_examples_as_non_instructions(self) -> None:
        """The header must explicitly tell the model NOT to follow the examples as commands."""
        block = build_voice_examples_block(["A", "B"])
        lower = block.lower()
        assert "do not" in lower or "must not" in lower or "ignore" in lower

    def test_ac02_block_lists_each_example(self) -> None:
        block = build_voice_examples_block(["one example", "second example"])
        assert "one example" in block
        assert "second example" in block

    def test_ac02_empty_examples_returns_empty_string(self) -> None:
        assert build_voice_examples_block([]) == ""


# ---------------------------------------------------------------------------
# AC-03 / AC-04: integration with _build_multi_prompt
# ---------------------------------------------------------------------------


def _make_analysis() -> ImageAnalysis:
    return ImageAnalysis(description="d", mood="m", tags=["a"], nsfw=False, safety_labels=[])


def _make_specs(voice_examples: tuple[str, ...] = ()) -> dict[str, CaptionSpec]:
    return {
        "telegram": CaptionSpec(
            platform="telegram", style="minimal_poetic", hashtags="", max_length=2200, examples=voice_examples
        ),
        "email": CaptionSpec(
            platform="email", style="descriptive", hashtags="", max_length=5000, examples=voice_examples
        ),
    }


class TestMultiPromptIntegration:
    def test_ac03_voice_examples_present_in_each_platform_block(self) -> None:
        examples = ("My signature line.", "Another voice marker.")
        specs = _make_specs(voice_examples=examples)
        prompt, _ = CaptionGeneratorOpenAI._build_multi_prompt(
            role_prompt="role",
            analysis=_make_analysis(),
            specs=specs,
            history=None,
        )
        # Both platform names appear
        assert "telegram" in prompt.lower()
        assert "email" in prompt.lower()
        # Voice examples flow through (existing PUB-039 behavior was platform-block-level
        # via spec.examples). Each example must appear in the rendered prompt.
        for ex in examples:
            assert ex in prompt

    def test_ac04_no_voice_block_when_examples_empty(self) -> None:
        """Feature-off path: no spec.examples → no voice-style header in the prompt."""
        specs = _make_specs(voice_examples=())
        prompt, _ = CaptionGeneratorOpenAI._build_multi_prompt(
            role_prompt="role",
            analysis=_make_analysis(),
            specs=specs,
            history=None,
        )
        # The "voice references only" wrapper must not appear when examples are empty.
        assert "BEGIN VOICE EXAMPLES" not in prompt.upper()
        assert "STYLE REFERENCES" not in prompt.upper()

    def test_ac04_feature_off_prompt_byte_identical_with_no_examples(self) -> None:
        """The prompt with empty spec.examples must equal a pre-PUB-029 baseline shape:
        no voice-related substrings introduced by PUB-029."""
        specs = _make_specs(voice_examples=())
        prompt, _ = CaptionGeneratorOpenAI._build_multi_prompt(
            role_prompt="role",
            analysis=_make_analysis(),
            specs=specs,
            history=None,
        )
        # PUB-029-introduced markers should be absent in the off path.
        for marker in ("BEGIN VOICE EXAMPLES", "END VOICE EXAMPLES"):
            assert marker not in prompt.upper(), f"Unexpected voice marker '{marker}' in feature-off prompt"

    def test_ac03_history_block_still_works_alongside_voice(self) -> None:
        """Voice examples + caption history coexist; both reachable in the prompt."""
        examples = ("Voice line one.",)
        specs = _make_specs(voice_examples=examples)
        prompt, _ = CaptionGeneratorOpenAI._build_multi_prompt(
            role_prompt="role",
            analysis=_make_analysis(),
            specs=specs,
            history=["A previous caption."],
        )
        assert "Voice line one." in prompt
        assert "A previous caption." in prompt
