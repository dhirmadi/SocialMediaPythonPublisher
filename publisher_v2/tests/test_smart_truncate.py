"""Tests for smart_truncate function in AI service."""

import pytest

from publisher_v2.services.ai import smart_truncate


class TestSmartTruncate:
    """Tests for smart_truncate caption length enforcement."""

    def test_no_truncation_when_under_limit(self) -> None:
        """Text under limit is returned unchanged."""
        text = "Short caption"
        result = smart_truncate(text, 100)
        assert result == text

    def test_no_truncation_when_exactly_at_limit(self) -> None:
        """Text exactly at limit is returned unchanged."""
        text = "x" * 50
        result = smart_truncate(text, 50)
        assert result == text

    def test_truncates_at_sentence_boundary(self) -> None:
        """Prefers cutting at sentence end when possible."""
        text = "First sentence. Second sentence that is much longer and exceeds the limit."
        result = smart_truncate(text, 50)
        # Should cut at first sentence since it's within the search window
        assert result == "First sentence."
        assert len(result) <= 50

    def test_truncates_at_word_boundary(self) -> None:
        """Falls back to word boundary when no sentence break available."""
        text = "This is a long caption without any sentence breaks anywhere in it"
        result = smart_truncate(text, 40)
        assert result.endswith("…")
        assert len(result) <= 40
        # Should not cut mid-word (ellipsis follows a complete word)
        assert result[-2] != " "  # Character before ellipsis is not a space

    def test_handles_question_mark_sentence_end(self) -> None:
        """Recognizes ? as sentence boundary."""
        text = "Is this a question? Here is more text that should be cut off."
        result = smart_truncate(text, 30)
        assert result == "Is this a question?"

    def test_handles_exclamation_sentence_end(self) -> None:
        """Recognizes ! as sentence boundary."""
        text = "Wow! This is exciting text that continues on and on."
        result = smart_truncate(text, 20)
        # With max 20, target is 19, "Wow!" is at index 3, search starts at 5
        # So "Wow!" should be found as sentence boundary
        assert result == "Wow!"

    def test_respects_max_length(self) -> None:
        """Result never exceeds max_length."""
        text = "A" * 500
        result = smart_truncate(text, 240)
        assert len(result) <= 240

    def test_adds_ellipsis_when_truncated_at_word(self) -> None:
        """Adds ellipsis when truncating at word boundary."""
        text = "The quick brown fox jumps over the lazy dog"
        result = smart_truncate(text, 25)
        assert result.endswith("…")

    def test_no_ellipsis_when_cut_at_sentence(self) -> None:
        """No ellipsis needed when cut at sentence end."""
        text = "Complete sentence. More text here that goes on and on."
        result = smart_truncate(text, 25)
        # With max 25, should cut at "Complete sentence."
        assert result == "Complete sentence."
        assert not result.endswith("…")

    def test_fetlife_limit_240(self) -> None:
        """Real-world test with FetLife's 240 char limit."""
        long_caption = (
            "A breathtaking figure study captures the interplay of light and shadow "
            "across carefully placed rope work. The composition draws the eye through "
            "geometric patterns while maintaining an intimate, contemplative mood. "
            "What draws your attention first in this artistic exploration?"
        )
        result = smart_truncate(long_caption, 240)
        assert len(result) <= 240
        # Should cut at a reasonable boundary
        assert result.endswith(".") or result.endswith("?") or result.endswith("…")

    def test_very_short_limit(self) -> None:
        """Handles very short limits gracefully."""
        text = "Hello world, this is a test"
        result = smart_truncate(text, 10)
        assert len(result) <= 10
        assert result.endswith("…")

    def test_custom_ellipsis(self) -> None:
        """Accepts custom ellipsis character."""
        text = "This text needs to be truncated to fit"
        result = smart_truncate(text, 20, ellipsis="...")
        assert result.endswith("...")
        assert len(result) <= 20
